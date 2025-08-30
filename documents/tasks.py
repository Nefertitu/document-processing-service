import os
# from datetime import datetime

from celery import shared_task
from django.core.cache import cache
from django.core.mail import send_mail
# from django.utils import timezone

from config import settings
from habits.models import Document

from users.models import User


@shared_task
def send_information(email):
    """Отправляет сообщение пользователю о создании документа"""

    try:
        user = User.objects.get(email=email)

        latest_document = Document.objects.filter(owner=user).order_by("-created_at").first()
        print(f"Последний документ: {latest_document}")

        if not latest_document:
            print(f"У пользователя {email} нет документов")
            return

        message_approve = f"Создан документ: {latest_document.title} - {latest_document.uploaded_at}. Документ ожидает подтверждения."

        if user.email and self.context["request"].method == 'POST' and self.action == "approve":
            send_mail(
                subject="Информация о создании документа",
                message=message_approve,
                from_email=os.getenv("EMAIL_HOST_USER"),
                recipient_list=[user.email, os.getenv("ADMIN_EMAIL")],
                fail_silently=False,
            )
            print(
                f"Создан документ: {latest_document.title}, ожидает подтверждения, уведомление отправлено на почту пользователю {latest_document.owner.email}"
            )
            # аналогично для reject
    except User.DoesNotExist:
        print(f"Пользователь с email '{email}' не найден")
    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")
