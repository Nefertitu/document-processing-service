from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Модель пользователя с кастомными полями.
    Заменяет стандартный `username` на `email`
    в качестве основного идентификатора."""

    username = None  # type: ignore[assignment]
    email = models.EmailField(
        unique=True,
        verbose_name="Email",
        help_text="Укажите email",
    )
    first_name = models.CharField(
        max_length=50,
        verbose_name="Имя пользователя",
        help_text="Укажите Ваше имя",
    )
    last_name = models.CharField(
        max_length=50,
        verbose_name="Фамилия пользователя",
        help_text="Укажите Вашу фамилию",
        blank=True,
    )
    avatar = models.ImageField(
        upload_to="users/avatars/",
        blank=True,
        null=True,
        verbose_name="Аватар",
        help_text="Загрузите свой аватар",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["last_name", "first_name"]

        permissions = [
            ("can_view_all_users", "Может видеть всех пользователей"),
            ("can_delete_user", "Может удалять пользователей"),
        ]

    @property
    def full_name(self):
        """Возвращает полное имя пользователя"""

        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return f"{self.first_name}"

    def __str__(self) -> str:
        """Строковое представление объекта пользователя"""
        return f"{self.first_name} {self.last_name} ({self.email})"

    # @property
    # def queue_size(self) -> int:
    #     """Количество документов в очереди администратора"""
    #     if hasattr(self, "approval_queue"):
    #         return self.approval_queue.items.count()
    #     return 0
    #
    # def get_queue_documents(self):
    #     """Документы в очереди администратора"""
    #     if hasattr(self, "approval_queue"):
    #         return self.approval_queue.items.order_by("position")
    #     return QueueItem.objects.none()
