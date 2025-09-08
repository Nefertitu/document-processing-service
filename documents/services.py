import os
import io
import uuid

from typing import Optional

from PIL import Image

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Count
from django.utils import timezone

from .tasks import archive_old_documents, send_single_document_email


User = get_user_model()


class DocumentFilePathGeneratorService:
    """Класс для генерации путей загрузки файлов документов"""

    @staticmethod
    def user_document_path(instance: models.Model, filename: str) -> str:
        """Путь для файлов, загружаемых пользователями"""
        return DocumentFilePathGeneratorService._generate_path(filename, "user", instance.owner.id)

    @staticmethod
    def admin_document_path(instance: models.Model, filename: str) -> str:
        """Путь для файлов, загружаемых администраторами"""

        admin_id = getattr(instance.assigned_admin, "id", "system")
        return DocumentFilePathGeneratorService._generate_path(filename, "admin", admin_id)

    @staticmethod
    def archived_document_path(instance: models.Model, filename: str) -> str:
        """Путь для архивных документов"""
        return DocumentFilePathGeneratorService._generate_path(filename, "archive", instance.owner.pk)

    @staticmethod
    def _generate_path(filename: str, prefix: str, user_id: Optional[int]) -> str:
        """
        Генерирует унифицированный путь для файла
        """

        ext = filename.split(".")[-1].lower()
        unique_filename = f"{uuid.uuid4().hex[:8]}.{ext}"

        return os.path.join("documents", f"{prefix}_{user_id}", unique_filename)

    @staticmethod
    def temp_upload_path(instance: models.Model, filename: str) -> str:
        """Путь для временных файлов"""

        ext = filename.split(".")[-1].lower()
        unique_filename = f"{uuid.uuid4().hex[:8]}.{ext}"
        return os.path.join("temp_uploads", unique_filename)


class DocumentHeavyProcessingService :
    """Класс для тяжелых операций"""

    @staticmethod
    def optimize_image(image_file):
        """Сжимает и оптимизирует изображение"""

        print(f"Получен файл: {image_file.name}, размер: {image_file.size}")
        try:
            img = Image.open(image_file)
            print(f"🖼 Изображение открыто: {img.size}, формат: {img.format}")

            img = img.resize((1200, 800), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85, optimize=True)
            print(f"Оптимизирован файл {img}, размер после оптимизации {img.size}")
            output.seek(0)

            return output
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            raise

def get_next_available_admin(exclude_admin=None):
    """Возвращает следующего доступного администратора"""

    from documents.models import QueueItem

    active_admins = User.objects.filter(is_staff=True, is_superuser=False, approval_queue__is_stop=False).distinct()

    if exclude_admin:
        active_admins = active_admins.exclude(id=exclude_admin.pk)

    if active_admins.exists():

        selected_admin = min(
            active_admins,
            key=lambda admin: QueueItem.objects.filter(queue__approver=admin, queue__is_stop=False).count(),
        )
        print(f"Выбран администратор: {selected_admin.email}")
        return selected_admin

    superuser = User.objects.filter(is_superuser=True).first()
    if superuser:
        print(f"Активных администраторов нет, назначен суперпользователь: {superuser}")
        return superuser

    print("Нет доступных администраторов!")
    return None


class FolderService:
    """Сервис для работы с папками документов"""

    @staticmethod
    def move_to_approved(document):
        """Перемещает в папку одобренных"""
        return FolderService.move_to_folder(document, "approved")

    @staticmethod
    def move_to_rejected(document):
        """Перемещает в папку отклоненных"""
        return FolderService.move_to_folder(document, "rejected")

    @staticmethod
    def move_to_folder(document, folder_slug):
        """Перемещает документ в указанную папку"""

        from .models import Folder

        try:
            print(f"Попытка перемещения документа {document.id} в папку {folder_slug}")
            folder = Folder.objects.get(slug=folder_slug)
            print(f"Найдена папка: {folder.title}")

            document.folder = folder
            document.save()

            print(f"✅ Документ '{document.title}' перемещен в папку '{folder.title}'")
            print(f"Текущая папка документа: {document.folder}")
            return True

        except Folder.DoesNotExist:
            print(f"❌ Папка {folder_slug} не найдена")
            return False
        except Exception as e:
            print(f"❌ Ошибка перемещения документа: {e}")
            return False

    @staticmethod
    def move_to_archive(document):
        """Перемещает в архив"""
        return FolderService.move_to_folder(document, "archived")


class DocumentService:
    """Сервис для работы с документами"""

    @staticmethod
    def create_document(validated_data, user, files_data):
        """Создание документа с бизнес-логикой"""

        from .models import ApprovalQueue, Document, Folder, QueueItem, DocumentFile

        try:
            pending_folder = Folder.objects.get(slug="pending")
            validated_data["folder"] = pending_folder

        except Folder.DoesNotExist:
            print("Папка 'pending' не найдена")
            pass

        document = Document.objects.create(**validated_data, owner=user)


        for file_data in files_data:
            DocumentFile.objects.create(
                document=document,
                file=file_data,
                original_name=file_data.name,
                owner=user
            )
            # if file_data and file_data.name.lower().endswith((".jpg", ".jpeg", ".png")):
            #     print(f"Загружается файл типа {type(document.file_data)}")
            #
            #     from .tasks import optimize_image_task
            #
            #     optimize_image_task.delay(document.pk)

        if not document.assigned_admin:
            document.assign_admin()

        if document.assigned_admin and document.status == "pending":
            QueueService.add_document_to_queue(document)
            FolderService.move_to_folder(document, folder_slug=document.status)
            print("Документ добавлен в папку 'На рассмотрении'")

        return document

    @staticmethod
    def handle_queue_action(item_id, user, action):
        """Обработка действий с документом в очереди (одобрение/отклонение)"""

        from .models import QueueItem

        message = ""
        try:
            queue_item = QueueItem.objects.select_related("document", "queue").get(id=item_id)
            document = queue_item.document

            print(f"Обработка документа: {document.title}, статус: {document.status}")

            if document.assigned_admin != user and not user.is_superuser:
                return {
                    "success": False,
                    "message": "Только ответственный администратор или суперпользователь может выполнять действия с документом",
                }

            if action == "approve":
                document.status = "approved"
                message = f"Документ '{document.title}' одобрен"
                document.reviewed_at = timezone.localtime()
                document.reviewed_by = user
                document.save()
                send_single_document_email.delay(
                    document_id=document.pk, status="approved", comment="Документ согласован!"
                )

                print(f"Статус изменен на: {document.status}")
                FolderService.move_to_approved(document)
                archive_old_documents.delay()


            elif action == "reject":
                document.status = "rejected"
                message = f"Документ '{document.title}' отклонен"
                document.reviewed_at = timezone.localtime()
                document.reviewed_by = user
                document.save()
                send_single_document_email.delay(
                    document_id=document.pk, status="rejected", comment="Документ отклонен!"
                )
                print(f"Статус изменен на: {document.status}")
                FolderService.move_to_rejected(document)
                archive_old_documents.delay()

            if queue_item:
                queue_item.delete()
                print(f"Элемент очереди {item_id} удален")

            QueueService.reorganize_queue(queue_item.queue)

            return {
                "success": True,
                "message": message,
                "document_id": document.pk
            }

        except Exception as e:
            print(f"Ошибка при обработке: {str(e)}")
            return {"success": False, "message": f"Ошибка: {str(e)}"}


    @staticmethod
    def move_to_new_queue(document, new_admin):
        """Перемещение документа в другую очередь"""

        from .models import QueueItem

        QueueItem.objects.filter(document=document).delete()

        document.assigned_admin = new_admin
        document.save()

        return QueueService.add_document_to_queue(document)

    def set_reviewed_at(self, document_id: int):
        """Устанавливает время утверждения документа"""

        document = Document.objects.get(pk=document_id)
        user = self.request.user

        if document and approve_document(self, request, object_id, item_id) or reject_document():
            now = timezone.localtime()
            document.reviewed_at = now
            document.save()
        return document


class QueueService:
    """Сервис для работы с очередями документов"""

    @staticmethod
    def add_document_to_queue(document):
        """Добавляет документ в очередь с автоматической позицией"""

        from .models import ApprovalQueue, Document, QueueItem

        print(f"Попытка добавить документ {document.title} в очередь")

        if not document.assigned_admin:
            print(f"Администратор: None - документ не будет добавлен в очередь")
            return False

        print(f"Администратор: {document.assigned_admin.email}")

        try:
            active_queues = ApprovalQueue.objects.filter(
                approver=document.assigned_admin,
                is_stop=False
            ).annotate(
            items_count=Count("items")
        )

            if not active_queues.exists():
                # Создаем новую очередь если нет активных
                queue = ApprovalQueue.objects.create(
                    approver=document.assigned_admin,
                    is_stop=False
                )

            elif active_queues.count() == 1:
                queue = active_queues.first()

            else:
                queue = active_queues.order_by("items_count").first()
                print(f"Выбрана очередь {queue.id} с {queue.items_count} документами")


            if not QueueItem.objects.filter(queue=queue, document=document).exists():
                item = QueueItem.objects.create(
                    queue=queue,
                    document=document,
                    position=ApprovalQueue.get_next_position(queue)
                )
                print(f"✅ Документ {document.id} добавлен в очередь: {item.id}")
                return True

            print(f"Очередь ID: {active_queue.pk}")
            print(f"Документов в очереди до включения в очередь: {active_queue.items.count()}")

            position = active_queue.items.count().get_next_position()
            print(f"Следующая позиция: {position}")

            queue_item = QueueItem.objects.create(queue=active_queue, document=document, position=position)
            print(f"Создан элемент QueueItem: {queue_item.id}")
            print(f"Документов в очереди после включения в очередь: {active_queue.items.count()}")

            return True

        except Exception as e:
            print(f"Ошибка добавления документа в очередь: {e}")
            return False

    @staticmethod
    def find_suitable_queue_for_document(document):
        """Найти или создать подходящую очередь для документа"""

        from .models import ApprovalQueue

        print(f"Попытка определить для документа {document.title} подходящую очередь")

        if not document.assigned_admin:
            print(f"Администратор: None - документ не будет добавлен в очередь")
            return None

        print(f"Администратор: {document.assigned_admin.email}")

        try:
            active_queues = ApprovalQueue.objects.filter(
                approver=document.assigned_admin,
                is_stop=False
            ).annotate(
                items_count=Count("items")
            )

            if not active_queues.exists():
                # Создаем новую очередь если нет активных
                queue = ApprovalQueue.objects.create(
                    approver=document.assigned_admin,
                    is_stop=False
                )
                print(f"Создан новая очередь: {queue.id}")

            elif active_queues.count() == 1:
                queue = active_queues.first()

            else:
                queue = active_queues.order_by("items_count").first()

            print(f"Выбрана очередь {queue.id} с {queue.items_count} документами")
            print(f"Документов в очереди после включения в очередь: {active_queue.items.count()}")

            return queue

        except Exception as e:
            print(f"Ошибка добавления документа в очередь: {e}")
            return None




    @staticmethod
    def get_or_create_queue(admin):
        """Получает или создает очередь для администратора"""

        from .models import ApprovalQueue

        queue, created = ApprovalQueue.objects.get_or_create(
            approver=admin, is_stop=False, defaults={"title": f"Очередь {admin.full_name}"}
        )
        return queue, created

    @staticmethod
    def reorganize_queue(queue):
        """Реорганизует позиции в очереди после удаления элемента"""

        from .models import QueueItem

        try:
            items = QueueItem.objects.filter(queue=queue).order_by('position')
            print(f"Реорганизация очереди {queue}, элементов: {items.count()}")
            for index, item in enumerate(items, start=1):
                if item.position != index:
                    print(f"Обновление позиции {item.position} -> {index}")
                    item.position = index
                    item.save(update_fields=["position"])

            print(f"Очередь {queue} успешно реорганизована")
            return True

        except Exception as e:
            print(f"Ошибка реорганизации очереди: {e}")
            return False

    @staticmethod
    def stop_queue(admin, title_queue):
        """Останавливает очередь администратора"""

        from .models import ApprovalQueue

        approval_queue = ApprovalQueue.objects.filter(approver=admin, title=title_queue, is_stop=False)

        if approval_queue:
            approval_queue.is_stop = True
            approval_queue.save()
            return True
        return False

    @staticmethod
    def resume_queue(admin, title_queue):
        """Возобновляет работу очереди администратора"""

        from .models import ApprovalQueue

        approval_queue = ApprovalQueue.objects.filter(approver=admin, title=title_queue, is_stop=True)

        if approval_queue:
            approval_queue.is_stop = False
            approval_queue.save()
            return True
        return False
