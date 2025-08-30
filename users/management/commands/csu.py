import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Команда для создания суперпользователя
    с предопределенными учетными данными"""

    help = "Создает кастомного суперпользователя"

    def handle(self, *args: Any, **options: Any) -> None:
        """Добавляет суперпользователю email, имя и пароль"""

        User = get_user_model()
        email = os.getenv("SUPERUSER_EMAIL", "superuser@example.com")
        password = os.getenv("SUPERUSER_PASSWORD", "123qwer")
        first_name = os.getenv("SUPERUSER_NAME", "superuser")

        if not User.objects.filter(email=email).exists():
            user = User.objects.create(
                email=email,
                first_name=first_name,
                is_active=True,
                is_staff=True,
                is_superuser=True,
            )
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully created user with email {user.email}!"))
        else:
            self.stdout.write(f"User with email {email} already exists")
