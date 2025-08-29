import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Команда для создания суперпользователя
    с предопределенными учетными данными"""

    help = "Создает кастомного суперпользователя"

    def handle(self, *args: Any, **options: Any) -> None:
        """Добавляет суперпользователю email и пароль"""

        User = get_user_model()
        email = os.getenv("SUPERUSER_EMAIL", "superuser@example.com")
        password = os.getenv("SUPERUSER_PASSWORD", "123qwer")

        if not User.objects.filter(email=email).exists():
            user = User.objects.create(email=email)
            user.set_password(password=password)
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully created user with email {user.email}!"))
        else:
            self.stdout.write(f"User with email {email} already exists")
