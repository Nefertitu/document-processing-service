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
    name = models.CharField(max_length=100, verbose_name="Имя пользователя", help_text="Укажите имя")
    avatar = models.ImageField(
        upload_to="users/avatars/", blank=True, null=True, verbose_name="Аватар", help_text="Загрузите свой аватар"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        """Строковое представление объекта пользователя"""
        return f"{self.name} ({self.email})"

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
