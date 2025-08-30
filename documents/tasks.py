import os
# from datetime import datetime

from celery import shared_task
from django.core.cache import cache
from django.core.mail import send_mail
# from django.utils import timezone

from config import settings
from documents.models import Document

from users.models import User
from django.contrib.auth import get_user_model

@shared_task
def send_document_status_email(document_id: int, status: str, comment: str = "") -> None:
    """Отправляет сообщение пользователю о создании документа"""

    User = get_user_model()

    try:
        document = Document.objects.get(pk=document_id)
        user = document.owner
        comment = document.review_comment

        if document.status == "pending":
            subject = "Ваш документ находится на рассмотрении"
            message = f"Документ '{document.title}' получен на рассмотрение {document.uploaded_at}."
            print(
                f"Создан документ: {ocument.title}, ожидает подтверждения, уведомление отправлено на почту пользователю {latest_document.owner.email}"
            )
        elif document.status == "approved":
            subject = "✅ Ваш документ подтвержден"
            message = f"Документ '{document.title}' был подтвержден."
            print(
                f"Подтвержден документ: {document.title}, уведомление отправлено на почту пользователю {document.owner.email}"
            )
        else:
            subject = "❌ Ваш документ отклонен"
            message = f"Документ '{document.title}' был отклонен."
            print(
                f"Отклонен документ: {document.title}, уведомление отправлено на почту пользователю {document.owner.email}"
            )

        latest_document = Document.objects.filter(owner=user).order_by("-created_at").first()
        print(f"Последний документ: {latest_document}")

        if comment:
            message += f"\nКомментарий: {document.review_comment}"

        if document.status == "pending":
            send_mail(
                subject=subject,
                message=message,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[os.getenv("ADMIN_PASSWORD")],
                fail_silently=False,
            )
        if user:
            send_mail(
                subject=subject,
                message=message,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[user.email],
                fail_silently=False,
            )

    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")
