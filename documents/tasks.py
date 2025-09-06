import io
import os
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
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
def send_bulk_documents_email(document_ids: list[int], status: str, general_comment: str = "") -> None:
    """Массовая отправка уведомлений - создает отдельные задачи для каждого документа"""

    for document_id in document_ids:
        # Для каждого документа создаем отдельную задачу
        send_single_document_email.delay(
            document_id=document_id, status=status, comment=general_comment  # Общий комментарий для всех
        )

    print(f"Создано {len(document_ids)} задач для отправки уведомлений")


@shared_task
def cleanup_temp_files():
    """Удаляет временные файлы старше 24 часов"""

    from .models import Document

    old_documents = Document.objects.filter(
        temp_file__isnull=False, uploaded_at__lt=timezone.now() - timedelta(hours=24)
    )

    for doc in old_documents:
        doc.temp_file.delete()  # Удаляет файл из storage
        doc.temp_file = None
        doc.save()


# @shared_task
# def process_document_task(document_id):
#     """Фоновая обработка документа"""
#
#     from .models import Document
#
#     document = Document.objects.get(id=document_id)
#     try:
#         processed_file = some_heavy_processing(document.file)
#         document.temp_file.save('processed.pdf', processed_file)
#         document.save()
#     except Exception as e:
#         logger.error(f"Ошибка обработки: {e}")


@shared_task
def optimize_image_task(document_id):
    """Фоновая оптимизация файлов"""

    from .models import Document
    from .services import DocumentHeavyProcessingService

    try:
        document = Document.objects.get(id=document_id)

        if not document.file:
            return

        optimized_image = DocumentHeavyProcessingService.optimize_image(document.file)
        document.temp_file.save("optimized.jpg", optimized_image)
        original_file = document.file
        document.temp_file = None
        document.save()

        original_file.delete()

    except Document.DoesNotExist:
        print(f"Документ {document_id} не найден")
    except Exception as e:
        print(f"Ошибка обработки: {e}")


@shared_task
def archive_old_documents():
    """Автоматически переносит в архив старые документы"""

    from .models import Document
    from .services import FolderService

    try:
        archive_date = timezone.localtime() - timedelta(minutes=5)
        old_documents = Document.objects.filter(
            reviewed_at__lte=archive_date, folder__slug__in=["approved", "rejected"]
        )
        print(f"Найдено документов для архивации: {old_documents.count()}")

        archived_count = 0
        for document in old_documents:
            print(f"Переносим в архив документ {document.id}: {document.title}")
            if FolderService.move_to_archive(document):
                archived_count += 1
                print(f"Документ {document.id} перенесен в папку 'архив'")

        print(f"Всего архивировано: {archived_count}")
        return archived_count

    except Exception as e:
        print(f"Ошибка переноса документов в архив: {e}")
        return 0
