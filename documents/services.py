import io
import os
import uuid
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model

# from django.core.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from PIL import Image
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response


from .tasks import archive_old_documents, send_single_document_email
from .validators import DocumentFileValidator

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

        admin_id = getattr(instance.document.assigned_admin, "id", "system")
        return DocumentFilePathGeneratorService._generate_path(filename, "admin", admin_id)

    # @staticmethod   # использование метода возможно при реализации цикла работы с архивными документами
    # def archived_document_path(instance: models.Model, filename: str) -> str:
    #     """Путь для архивных документов"""
    #     return DocumentFilePathGeneratorService._generate_path(filename, "archive", instance.owner.pk)

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


class DocumentHeavyProcessingService:
    """Сервис для тяжелых операций с документами"""

    MAX_SIZE_MB = 0.1
    MAX_WIDTH = 1200
    MAX_HEIGHT = 800

    @staticmethod
    def optimize_image(image_file):
        """Сжимает и оптимизирует изображение"""

        file_size_mb = image_file.size / (1024 * 1024)

        if file_size_mb < DocumentHeavyProcessingService.MAX_SIZE_MB:
            print(f"📦 Файл {image_file.name} ({file_size_mb:.2f} MB) слишком мал для оптимизации")
            return None

        print(f"⚙️ Оптимизируем: {image_file.name} ({file_size_mb:.1f} MB)")

        try:
            img = Image.open(image_file)
            print(f"🖼 Исходный размер: {img.size}")

            if (
                img.size[0] > DocumentHeavyProcessingService.MAX_WIDTH
                or img.size[1] > DocumentHeavyProcessingService.MAX_HEIGHT
            ):
                img.thumbnail(
                    (DocumentHeavyProcessingService.MAX_WIDTH, DocumentHeavyProcessingService.MAX_HEIGHT),
                    Image.Resampling.LANCZOS,
                )
                print(f"📐 Новый размер: {img.size}")

            output = io.BytesIO()

            if img.format == "PNG":
                if img.mode in ("RGBA", "LA"):
                    img = img.convert("RGB")
                img.save(output, format="JPEG", quality=85, optimize=True)
            else:
                img.save(output, format=img.format, quality=85, optimize=True)

            output.seek(0)
            print("✅ Оптимизация завершена")

            return output

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None

    def generate_test_image_content(width=1000, height=1000, format="JPEG"):
        """Генерирует тестовое изображение в памяти"""

        import io

        from PIL import Image, ImageDraw

        # Создаем изображение с градиентом
        img = Image.new("RGB", (width, height), color="red")
        draw = ImageDraw.Draw(img)

        # Добавляем некоторые детали, чтобы увеличить размер файла
        for i in range(0, width, 50):
            draw.line([(i, 0), (i, height)], fill="blue", width=2)
        for i in range(0, height, 50):
            draw.line([(0, i), (width, i)], fill="green", width=2)

        # Сохраняем в BytesIO
        output = io.BytesIO()
        img.save(output, format=format, quality=95)  # Высокое качество = большой размер
        output.seek(0)

        return output.getvalue()


def get_next_available_admin(exclude_admin=None):
    """Возвращает следующего доступного администратора"""

    from documents.models import QueueItem

    active_admins = (
        User.objects.filter(is_staff=True, is_superuser=False, approval_queue__is_stop=False)
        .annotate(task_count=Count("approval_queue", filter=Q(approval_queue__is_stop=False)))
        .distinct()
    )

    if exclude_admin:
        active_admins = active_admins.exclude(id=exclude_admin.pk)

    if active_admins.exists():

        selected_admin = active_admins.order_by("task_count").first()
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

            old_folder = document.folder
            old_status = document.status

            document.folder = folder
            document.status = folder_slug
            document.save()

            print(f"✅ Документ '{document.title}' перемещен:")
            print(f"   Папка: {old_folder} → {document.folder}")
            print(f"   Статус: {old_status} → {document.status}")

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

        from .models import ApprovalQueue, Document, DocumentFile, Folder, QueueItem

        if not files_data:
            raise DjangoValidationError("Загрузите хотя бы один файл!")

        file_validator = DocumentFileValidator()

        # Проверяем все файлы перед созданием документа
        for file_data in files_data:
            try:
                file_validator({"file": file_data})
            except DRFValidationError as e:
                raise DjangoValidationError(e.detail)

        try:
            pending_folder = Folder.objects.get(slug="pending")
            validated_data["folder"] = pending_folder

        except Folder.DoesNotExist:
            print("Папка 'pending' не найдена")
            pass

        document = Document.objects.create(**validated_data, owner=user)

        print(f"📄 Создан документ {document.id} с {len(files_data)} файлами")

        for file_data in files_data:
            document_file = DocumentFile.objects.create(document=document, file=file_data, owner=user)
            print(f"📝 Создан DocumentFile ID: {document_file.id}")
            print(f"📦 Имя файла: {document_file.file.name}")
            print(f"📊 Размер: {document_file.file.size}")

            if file_data and file_data.name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
                print(f"🚀 Запуск оптимизации для файла: {file_data.name}")

                from .tasks import optimize_image_task

                optimize_image_task.delay(document_file.pk)

        if not document.assigned_admin:
            document.assign_admin()

        if document.assigned_admin and document.status == "pending":
            QueueService.add_document_to_queue(document)
            FolderService.move_to_folder(document, folder_slug=document.status)
            print("Документ добавлен в папку 'На рассмотрении'")

        return document

    @staticmethod
    def handle_queue_action(item_id, user, action, temp_review_comment="", temp_file_answer=None):
        """Обработка действий с документом в очереди (одобрение/отклонение)"""

        from .models import QueueItem

        message = ""
        try:
            queue_item = QueueItem.objects.select_related("document", "queue").get(id=item_id)
            document = queue_item.document
            # review_comment = document.review_comment
            # file_answer = document.file_answer

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
                # if review_comment:
                #     document.review_comment = review_comment
                # if file_answer:
                #     document.file_answer = file_answer
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
                # if review_comment:
                #     document.review_comment = review_comment
                # if file_answer:
                #     document.file_answer = file_answer
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

            return {"success": True, "message": message, "document_id": document.pk}

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

        from .models import Document

        document = Document.objects.get(pk=document_id)

        if document.status in ["approved", "rejected"]:
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
            print("Администратор: None - документ не будет добавлен в очередь")
            return None

        print(f"Администратор: {document.assigned_admin.email}")

        try:
            active_queues = ApprovalQueue.objects.filter(approver=document.assigned_admin, is_stop=False).annotate(
                items_count=Count("items")
            )

            if not active_queues.exists():
                # Создаем новую очередь если нет активных
                queue = ApprovalQueue.objects.create(approver=document.assigned_admin, is_stop=False)
                print(f"Создана новая очередь: {queue.id}")

            elif active_queues.count() == 1:
                queue = active_queues.first()

            else:
                queue = active_queues.order_by("items_count").first()
                print(f"Выбрана очередь {queue.id} с {queue.items_count} документами")

            if not QueueItem.objects.filter(queue=queue, document=document).exists():
                item = QueueItem.objects.create(
                    queue=queue, document=document, position=ApprovalQueue.get_next_position(queue)
                )
                print(f"✅ Документ {document.id} добавлен в очередь: {item.id}")
                return True

            print(f"Очередь ID: {queue.pk}")
            print(f"Документов в очереди до включения в очередь: {queue.items.count()}")

            position = queue.items.count().get_next_position()
            print(f"Следующая позиция: {position}")

            queue_item = QueueItem.objects.create(queue=queue, document=document, position=position)
            print(f"Создан элемент QueueItem: {queue_item.id}")
            print(f"Документов в очереди после включения в очередь: {queue.items.count()}")

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
            print("Администратор: None - документ не будет добавлен в очередь")
            return None

        print(f"Администратор: {document.assigned_admin.email}")

        try:
            active_queues = ApprovalQueue.objects.filter(approver=document.assigned_admin, is_stop=False).annotate(
                items_count=Count("items")
            )

            if not active_queues.exists():
                # Создаем новую очередь если нет активных
                queue = ApprovalQueue.objects.create(approver=document.assigned_admin, is_stop=False)
                print(f"Создан новая очередь: {queue.id}")

            elif active_queues.count() == 1:
                queue = active_queues.first()

            else:
                queue = active_queues.order_by("items_count").first()

            print(f"Выбрана очередь {queue.id} с {queue.items_count} документами")
            print(f"Документов в очереди после включения в очередь: {queue.items.count()}")

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
            items = QueueItem.objects.filter(queue=queue).order_by("position")
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


def setup_task_archive_old_documents(document_id):
    """Устанавливаем расписание для выполнения переноса документов в папку 'архив'"""

    from .models import Document

    document = Document.objects.get(id=document_id)

    if document:

        if not PeriodicTask.objects.filter(task="documents.tasks.archive_old_documents").exists():
            schedule, created = IntervalSchedule.objects.get_or_create(
                every=5,
                period=IntervalSchedule.MINUTES,
            )

            task, created = PeriodicTask.objects.get_or_create(
                name="Archive old documents daily",
                task="documents.tasks.archive_old_documents",
                interval=schedule,
                enabled=True,
            )

            print("✅ Задача создана!")

        else:
            print("ℹ️ Задача архивации уже существует")
