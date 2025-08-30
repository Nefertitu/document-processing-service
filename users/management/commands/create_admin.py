import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    """Команда для создания администратора с данными из переменных окружения"""
    
    help = "Создает администратора из переменных окружения"

    def handle(self, *args: Any, **options: Any) -> None:
        """Добавляет администратору email, имя и пароль"""
        
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")
        first_name = os.getenv("ADMIN_FIRST_NAME")

        if not email or not password or not first_name:
            self.stdout.write(self.style.WARNING("ADMIN_EMAIL, ADMIN_PASSWORD или ADMIN_FIRST_NAME не установлены"))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f"Администратор с таким email:{email}, - уже существует"))
            return

        admin_user = User.objects.create(
            email=email,
            first_name=first_name,
            is_active=True,
            is_staff=True,
        )
        admin_user.set_password(password)
        admin_user.save()

        self.stdout.write(self.style.SUCCESS(f"Администратор c email: {email} создан"))