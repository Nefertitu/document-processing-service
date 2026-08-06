import os
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    """
    Универсальная команда для создания суперпользователя и администратора.
    """

    help = "Создает суперпользователя и администратора из переменных окружения"

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('СОЗДАНИЕ ПОЛЬЗОВАТЕЛЕЙ'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        # 1. Создаем суперпользователя
        self._create_superuser()

        # 2. Создаем администратора
        self._create_admin()

        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('✅ СОЗДАНИЕ ПОЛЬЗОВАТЕЛЕЙ ЗАВЕРШЕНО'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

    def _create_superuser(self) -> None:
        """Создает суперпользователя из переменных окружения"""
        email = os.getenv('SUPERUSER_EMAIL')
        password = os.getenv('SUPERUSER_PASSWORD')
        first_name = os.getenv('SUPERUSER_FIRST_NAME', 'Super')

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                '⚠️ Пропускаем создание суперпользователя: '
                'не заданы SUPERUSER_EMAIL или SUPERUSER_PASSWORD'
            ))
            return

        # Проверяем, существует ли пользователь
        if User.objects.filter(email=email).exists():
            user = User.objects.get(email=email)
            self.stdout.write(self.style.WARNING(
                f'ℹ️ Суперпользователь {email} уже существует'
            ))

            # Проверяем, является ли пользователь суперпользователем
            if not user.is_superuser:
                user.is_superuser = True
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Пользователь {email} повышен до суперпользователя'
                ))

            # Добавляем в группу documents_admin
            self._add_to_group(user)
            return

        # Создаем суперпользователя
        user = User.objects.create(
            username=email.split('@')[0] + '_super',
            email=email,
            first_name=first_name,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Суперпользователь c email: {email} создан'))

        # Добавляем в группу documents_admin
        self._add_to_group(user)


    def _create_admin(self) -> None:
        """Создает обычного администратора из переменных окружения"""
        email = os.getenv('ADMIN_EMAIL')
        password = os.getenv('ADMIN_PASSWORD')
        first_name = os.getenv('ADMIN_FIRST_NAME', 'Admin')

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                '⚠️ Пропускаем создание администратора: '
                'не заданы ADMIN_EMAIL или ADMIN_PASSWORD'
            ))
            return

        # Проверяем, существует ли пользователь
        if User.objects.filter(email=email).exists():
            user = User.objects.get(email=email)
            self.stdout.write(self.style.WARNING(
                f'ℹ️ Администратор {email} уже существует'
            ))

            # Проверяем, является ли пользователь staff
            if not user.is_staff:
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Пользователь {email} повышен до администратора'
                ))

            # Добавляем в группу documents_admin
            self._add_to_group(user)
            return

        # Создаем администратора
        user = User.objects.create(
            username=email.split('@')[0],
            email=email,
            first_name=first_name,
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Администратор с email: {email} создан'))

        # Добавляем в группу documents_admin
        self._add_to_group(user)

    def _add_to_group(self, user: User) -> None:
        """Добавляет пользователя в группу documents_admin"""
        try:
            group, created = Group.objects.get_or_create(name='documents_admin')
            if created:
                self.stdout.write(self.style.WARNING(
                    f'⚠️ Группа {group.name} создана, но права не назначены. '
                    'Загрузите фикстуру groups.json для назначения прав.'
                ))

            user.groups.add(group)
            self.stdout.write(self.style.SUCCESS(
                f'Пользователь {user.email} добавлен в группу {group.name}'
            ))

            # Выводим количество прав в группе
            perms_count = group.permissions.count()
            self.stdout.write(f'   Прав в группе: {perms_count}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'❌ Ошибка при добавлении в группу: {e}'
            ))