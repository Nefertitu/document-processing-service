from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.dispatch import receiver


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"

    def ready(self):
        """Сигнал для вызова метода создания папок"""

        from .models import Folder

        def create_system_folders(sender, **kwargs):
            """Вызывает метод создания системных папок"""

            Folder.ensure_system_folders()

        post_migrate.connect(create_system_folders, sender=self)