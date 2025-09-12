import io
import os
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from django.db.models import Q
from PIL import Image

from config import settings
from users.models import User


@shared_task
def send_single_document_email(document_id: int, status: str, comment: str = "") -> None:
    """Отправляет сообщение пользователю о создании документа"""

    from .models import Document

    try:
        document = Document.objects.get(id=document_id)
        user = document.owner
        comment = document.review_comment

        print(f"Попытка отправки email на: {user.email}")
        print(f"От: {settings.DEFAULT_FROM_EMAIL}")
        print(f"Тема: {document.title}")

        if status == "pending":
            subject = "Получен документ на согласование"
            message = f"Документ '{document.title}' создан {document.uploaded_at}, ожидает подтверждения."
            print(
                f"Создан документ: {document.title}, ожидает подтверждения, уведомление отправлено на почту пользователю {document.owner.email}"
            )
            result = send_mail(
                subject=subject,
                message=message,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[document.assigned_admin.email],
                fail_silently=False,
            )
            print(f"Результат отправки: {result}")

        elif status == "approved":
            subject = "✅ Ваш документ подтвержден"
            message = f"Документ '{document.title}' был подтвержден."

            if comment:
                message += f"\nКомментарий: {comment}"

            result = send_mail(
                subject=subject,
                message=message,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[document.owner.email],
                fail_silently=False,
            )
            print(
                f"Подтвержден документ: {document.title}, уведомление отправлено на почту пользователю {document.owner.email}"
            )
            print(f"Результат отправки: {result}")

        elif status == "rejected":
            subject = "❌ Ваш документ отклонен"
            message = f"Документ '{document.title}' был отклонен."

            if comment:
                message += f"\nКомментарий: {comment}"

            result = send_mail(
                subject=subject,
                message=message,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[document.owner.email],
                fail_silently=False,
            )
            print(f"Результат отправки: {result}")
            print(f"Отправлено уведомление пользователю {user.email} о статусе документа: {status}")
            print(
                f"Отклонен документ: {document.title}, уведомление отправлено на почту пользователю {document.owner.email}"
            )

    except Exception as e:
        print(f"Ошибка при отправке сообщения: {str(e)}")


@shared_task
def optimize_image_task(document_file_id):
    """Фоновая оптимизация файлов"""

    print(f"🎯 START: Задача оптимизации для файла ID: {document_file_id}")

    try:
        from .models import Document, DocumentFile
        from .services import DocumentHeavyProcessingService
        import os

        print(f"🔍 Поиск файла с ID: {document_file_id}")
        document_file = DocumentFile.objects.get(id=document_file_id)
        print(f"✅ Файл найден: {document_file.id}")
        print(f"🔄 Начинаем оптимизацию файла ID: {document_file_id}")
        print(
            f"📊 Статистика: документ {document_file.document.id} "
            f"имеет {document_file.document.additional_files.count()} файлов")

        if not document_file.file:
            print(f"❌ У файла нет содержимого")
            return
        print("Найдены файлы оптимизации")

        print(f"📁 Обрабатываем: {document_file.file.name}")
        original_filename = os.path.basename(document_file.file.name)
        print(f"🔄 Оптимизация файла: {original_filename} (ID: {document_file_id})")

        print(f"⚙️ Вызов DocumentHeavyProcessingService.optimize_image")
        optimized_image = DocumentHeavyProcessingService.optimize_image(document_file.file)

        if optimized_image:
            print(f"💾 Сохранение оптимизированного файла")
            document_file.file.save(
                original_filename,
                optimized_image,
                save=True
            )
            # print(f"✅ Успешно оптимизирован файл ! Размер: {len(optimized_image.getvalue())} bytes")
            print(f"✅ Файл {original_filename} оптимизирован и сохранен")
            return "success"
        else:
            print(f"⚠️ Не удалось оптимизировать файл {original_filename}")
            return "skipped"

    except Document.DoesNotExist:
        print(f"❌ Файл документа {document_id} не найден")
    except Exception as e:
        print(f"❌ Ошибка обработки: {e}")

        import traceback

        traceback.print_exc()
        return "error"


@shared_task
def archive_old_documents():
    """Автоматически переносит в архив старые документы"""

    from .models import Document
    from .services import FolderService
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Q

    try:
        archive_date = timezone.localtime() - timedelta(minutes=5)
        print(f"Дата архивации по времени 'since reviewed_at': {archive_date}")

        archive_date_created = timezone.localtime() - timedelta(hours=1)
        print(f"Дата архивации по времени 'since created_at': {archive_date_created}")

        old_documents = Document.objects.filter(
            Q(reviewed_at__lte=archive_date, status__in=["approved", "rejected"]) |
            Q(uploaded_at__lte=archive_date_created, status__in=["approved", "rejected"])
            ).exclude(status="archived")

        print(f"Найдено документов для архивации: {old_documents.count()}")

        archived_count = 0
        for document in old_documents:
            try:
                print(f"Переносим в архив документ {document.id}: {document.title}")



                if FolderService.move_to_archive(document):
                    print(f"Статус документа после переноса: {document.status}")

                    archived_count += 1

                    print(f"✓ Документ {document.id} перенесен в папку 'архив'")
                else:
                    print(f"✗ Ошибка перемещения документа {document.id}")

            except Exception as e:
                print(f"✗ Ошибка архивации документа {document.id}: {e}")
                continue

        print(f"Всего архивировано: {archived_count}")
        return archived_count

    except Exception as e:
        print(f"✗ Ошибка переноса документов в архив: {e}")
        return 0
