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
        2. Размер загружаемого изображения не может превышать 4MB
        """

        file_data = data.get("files") or data.get("file")

        if not file_data:
            raise serializers.ValidationError()

        max_size = 4 * 1024 * 1024

        if file_data.size > max_size:
            raise serializers.ValidationError(
                f"'file': Файл слишком большой ({filesizeformat(file_data.size)})! "
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
        3. Минимум 3 символа в названии др.условия
        """

        print(f"🔍 Validating title: '{data.get('title')}'")
        self.instance = getattr(self, "instance", None)
        self.partial_update = getattr(self, "partial", True)

        if not isinstance(data, dict):
            return

        # title_data = data.get("title", getattr(self.instance, "title", None))
        title_data = data.get("title")

        if not title_data or not title_data.strip():
            return

        re_forbidden = rf'\b({"|".join(re.escape(word) for word in self.FORBIDDEN_WORDS)})\b'
        lower_value = title_data.lower()
        found_words = []

        for word in self.FORBIDDEN_WORDS:
            if re.search(word, lower_value, re.IGNORECASE):
                found_words.append(word)

        if re.search(re_forbidden, lower_value, re.IGNORECASE):
            raise serializers.ValidationError(
                f'Нельзя использовать запрещенные слова ({", ".join(found_words)}) в названии и/или описании!'
            )

        re_pattern = r"^[a-zA-Zа-яА-ЯёЁ0-9][a-zA-Zа-яА-ЯёЁ0-9\-_\ ]+$"
        if not re.search(re_pattern, title_data):
            raise serializers.ValidationError(
                "Название может состоять из русских и английских букв, "
                "цифр, пробелов, дефисов (-) и подчеркиваний (_)!"
            )
        if len(title_data) < 3:
            raise serializers.ValidationError(
                "Название должно содержать минимум 3 символа!"
            )
        if not any(char.isalpha() for char in title_data):
            raise serializers.ValidationError(
                "Название должно содержать хотя бы одну букву!"
            )
        print("✅ Validation passed")
