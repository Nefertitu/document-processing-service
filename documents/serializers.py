from typing import Optional

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from documents.models import Folder, Document
# from habits.validators import FrequencyValidator, LeadTimeValidator, RequiredFieldTimeValidator, RewardHabitValidator


class FolderSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'Folder'"""

    title = serializers.CharField(
        required=True,
        error_messages={
            "required": "Это поле обязательно для заполнения!",
            "null": "Данное поле не может иметь значение null!",
        },
    )
    owner = serializers.SerializerMethodField()

    def get_owner(self, instance: Folder) -> Optional[str]:
        """Возвращает 'email' пользователя-создателя папки"""
        return str(instance.owner.email) if instance.owner else None

    class Meta:
        model = Folder
        fields = "__all__"


class DocumentSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'Document'"""

    title = serializers.CharField(
        required=True,
        error_messages={
            "required": "Это поле обязательно для заполнения!",
            "null": "Данное поле не может иметь значение null!",
        },
    )
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True)
    file_url = serializers.SerializerMethodField()

    def get_serializer_context(self):
        """Добавляем request в контекст сериализатора"""

        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_file_url(self, obj):
        """Возвращает абсолютный путь до файла"""

        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None

    class Meta:
        model = Document
        fields = ["id", "title", "description", "owner_email", "owner_name", "file_url", "status", "uploaded_at"]
        read_only_fields = ["status", "uploaded_at"]


class DocumentAdminSerializer(serializers.ModelSerializer):
    """Сериализатор для администраторов (полные права)"""
    
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "description", "file", "status", "uploaded_at",
                  "reviewed_at", "reviewed_by", "review_comment", "owner",
                  "owner_email", "owner_name"]
        read_only_fields = ["uploaded_at"] 




