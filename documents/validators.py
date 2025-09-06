import re
from datetime import datetime, time, timedelta
from typing import Any

from django.template.defaultfilters import filesizeformat
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


class DocumentFileValidator:
    """Класс-валидатор для проверки поля 'file' экземпляра 'Document'"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Класс-валидатор работает с фиксированными полями"""
        pass

    def __call__(self, data: dict) -> None:
        """
        Проверяет:
        1. Обязательность поля 'file'
        2. Размер загружаемого изображения не может превышать 10MB
        """

        self.instance = getattr(self, "instance", None)
        self.partial_update = getattr(self, "partial", True)

        file_data = data.get("file", getattr(self.instance, "file", False))

        if not file_data:
            raise serializers.ValidationError()

        max_size = 4 * 1024 * 1024

        if file_data.size > max_size:
            raise ValidationError(
                f"'file': Файл слишком большой ({filesizeformat(file_data.size)}). "
                f"Допустимый размер - до {filesizeformat(max_size)}."
            )


class TitleValidator:
    """Класс-валидатор для проверки поля 'title'"""

    FORBIDDEN_WORDS = ["казино", "криптовалюта", "крипта", "биржа", "дешево", "бесплатно", "обман", "полиция", "радар"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Класс-валидатор работает с фиксированными полями"""
        pass

    def __call__(self, data: dict) -> None:
        """
        Проверяет:
        1. Обязательность поля 'title'
        2. Отсутствие запрещенных слов в названии
        """

        self.instance = getattr(self, "instance", None)
        self.partial_update = getattr(self, "partial", True)

        title_data = data.get("title", getattr(self.instance, "title", None))

        if not title_data:
            raise serializers.ValidationError()

        re_forbidden = rf'\b({"|".join(re.escape(word) for word in self.FORBIDDEN_WORDS)})\b'
        lower_value = title_data.lower()
        found_words = []

        for word in self.FORBIDDEN_WORDS:
            if re.search(word, lower_value, re.IGNORECASE):
                found_words.append(word)

        if re.search(re_forbidden, lower_value, re.IGNORECASE):
            raise ValidationError(
                f'Нельзя использовать запрещенные слова ({", ".join(found_words)}) в названии и/или описании'
            )
