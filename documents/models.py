from django.db import models
from django.contrib.auth import get_user_model
from config import settings


User = get_user_model()


class Folder(models.Model):
    """Модель Папка"""

    title = models.CharField(
        max_length=100,
        verbose_name="Название папки",
        default="Мои документы",
        help_text="Заполните название папки",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Владелец папки",
        related_name="folders",
    )
    created_at = models.DateTimeField(
        verbose_name="Дата создания",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Папка"
        verbose_name_plural = "Папки"
        unique_together = ["title", "owner"]

    def __str__(self) -> str:
        """Строковое отображение модели Папка"""
        return self.title


class Document(models.Model):
    """Модель Документ"""

    STATUS_CHOICES = (
        ("pending", "На рассмотрении"),
        ("approved", "Подтвержден"),
        ("rejected", "Отклонен"),
    )

    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        verbose_name="Название папки",
        related_name="documents",
        null=True,
        blank=True,
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Название документа",
        help_text="Укажите название документа",
    )
    description = models.TextField(
        verbose_name="Описание",
        blank=True,
        help_text="Введите описание документа",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=False,
        null=False,
        verbose_name="Владелец",
        help_text="Укажите владельца документа",
        related_name="documents",
    )
    file = models.FileField(
        verbose_name="Файл",
        upload_to=f"documents/%Y/%m/%d/",
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        verbose_name="Статус документа",
        default="pending",
    )
    uploaded_at  = models.DateTimeField(
        verbose_name="Дата и время загрузки документа",
        auto_now_add=True,
    )
    reviewed_at = models.DateTimeField(
        verbose_name="Дата и время проверки",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Проверивший администратор",
        null=True,
        blank=True,
        related_name="reviewed_documents"
    )
    review_comment = models.TextField(
        verbose_name="Комментарий при проверке",
        blank=True,
    )

    class Meta:
        verbose_name = "Документ"
        verbose_name_plural = "Документы"
        ordering = ["-uploaded_at"]

        permissions = [
            ("view_all_documents", "Может видеть все документы"),
            ("can_approve_document", "Может подтверждать документы"),
            ("can_reject_document", "Может отклонять документы"),
        ]

    def __str__(self) -> str:
        """Строковое отображение модели Документ"""
        return f"{self.title} ({self.owner.name}, {self.owner.email})"

    def intelligible_file_path(instance, filename):
        """Сохраняем по дате, но логически группируем через модель"""

        # Физически: по дате для эффективности
        base_path = f"documents/%Y/%m/%d/"

        # Логически: связываем через ForeignKey в БД
        # Папка существует только как запись в базе данных
        return base_path + filename

