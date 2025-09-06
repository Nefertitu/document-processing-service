import os
from typing import Optional

from django.conf import settings
from django.db.models import Count
from django.urls import path
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.validators import UniqueValidator

from users.models import User

from .models import ApprovalQueue, Document, Folder, QueueItem
from .validators import DocumentFileValidator, TitleValidator


class FolderSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'Folder'"""

    documents_count = serializers.SerializerMethodField()
    title = serializers.CharField(
        required=True,
        validators=[TitleValidator(field="title")],
        error_messages={
            "required": "Поле обязательно для заполнения!",
            "blank": "Поле не может быть пустым!",
            "null": "Поле не может иметь значение null!",
        },
    )
    description = serializers.CharField(
        validators=[TitleValidator(field="description")],
    )
    slug = serializers.SlugField(
        max_length=20,
        min_length=3,
        required=True,
        validators=[
            UniqueValidator(
                queryset=Folder.objects.all(),
                message="Папка с таким идентификатором уже существует!",
            )
        ],
        error_messages={
            "required": "Поле обязательно для заполнения!",
            "null": "Поле не может иметь значение null!",
            "blank": "Поле не может быть пустым!",
            "invalid": "Поле может содержать только латинские буквы, цифры, дефисы и подчеркивания!",
            "unique": "Поле с таким названием уже существует!",
            "max_length": "Максимальная длина - 20 символов!",
            "min_length": "Минимальная длина - 3 символа!",
        },
    )

    def get_documents_count(self, obj):
        """Возвращает количество документов в папках"""
        return obj.documents.count()

    class Meta:
        model = Folder
        fields = (
            "id",
            "title",
            "slug",
            "description",
            "documents_count",
            "created_at",
        )
        read_only_fields = (
            "slug",
            "created_at",
        )
        validators = [TitleValidator(field="title")]


class BaseDocumentSerializer(serializers.ModelSerializer):
    """Базовый сериализатор с общей логикой"""

    def get_serializer_context(self):
        """Добавляем request в контекст сериализатора"""

        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class DocumentSerializer(BaseDocumentSerializer):
    """
    Сериализатор для модели 'Document' для пользователей,
    которые ЗАГРУЖАЮТ документы.
    Могут: загружать документы, видеть статус, своего администратора.
    Не могут: менять статус, reviewer_info, все поля владельца.
    """

    title = serializers.CharField(
        required=True,
        error_messages={
            "required": "Поле обязательно для заполнения!",
            "blank": "Поле не может быть пустым!",
        },
    )
    description = serializers.CharField(
        validators=[TitleValidator(field="description")],
        required=False,
        allow_blank=True,
    )
    review_comment = serializers.CharField(
        validators=[TitleValidator(field="description")],
        required=False,
        allow_blank=True,
    )
    assigned_admin = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    file = serializers.FileField(
        required=True,
        error_messages={
            "required": "Загрузите файл!",
            "invalid": "Отправленные данные не являются файлом. Проверьте тип кодировки в форме!",
        },
    )

    def create(self, validated_data: dict) -> Document:
        """
        Создает документ и автоматически назначает администратора,
        если он не был указан явно
        """

        try:
            document = Document.objects.create(**validated_data)

            if not document.assigned_admin:
                document.assign_admin()
                document.save()
            return document

        except Exception as e:
            raise serializers.ValidationError(f"Не удалось создать документ: {str(e)}")

    def get_owner(self, instance: Document) -> Optional[str]:
        """Возвращает email пользователя-создателя привычки"""
        return str(instance.owner.email) if instance.owner else None

    def get_assigned_admin(self, obj):
        """Добавляет информацию об администраторе"""

        if obj.assigned_admin:
            return {"email": obj.assigned_admin.email, "full_name": obj.assigned_admin.get_full_name()}
        return None

    class Meta:
        model = Document
        fields = ["id", "title", "assigned_admin", "description", "file", "status", "uploaded_at", "owner", "review_comment"]
        read_only_fields = ["status", "uploaded_at", "owner"]
        validators = [DocumentFileValidator(), TitleValidator(field="title")]


class DocumentAdminSerializer(BaseDocumentSerializer):
    """
    Сериализатор для администраторов (полные права).
    Могут: видеть все поля и менять статус, reviewer_info.
    Видят: полную информацию о владельце.
    """

    assigned_admin = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True)
    review_comment = serializers.CharField(
        validators=[TitleValidator(field="description")],
    )

    def get_assigned_admin(self, obj):
        """Добавляет информацию об администраторе"""

        if obj.assigned_admin:
            return {
                "id": obj.assigned_admin.pk,
                "email": obj.assigned_admin.email,
                "full_name": obj.assigned_admin.get_full_name(),
            }
        return None

    def get_file_url(self, obj):
        """Возвращает абсолютный путь до файла"""

        if obj.file:
            print(f"obj.file: {obj.file}")
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.file.url)
            else:
                if settings.DEBUG:

                    return f"http://localhost:8000{obj.file.url}"
                else:
                    return f"https://{os.getenv("SERVER_IP")}{obj.file.url}"  # ???
        return None

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "description",
            "file",
            "file_url",
            "status",
            "uploaded_at",
            "reviewed_at",
            "review_comment",
            "owner",
            "owner_email",
            "owner_name",
        ]
        read_only_fields = ["title", "description", "owner", "file", "uploaded_at"]


class ApprovalQueueSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'ApprovalQueue'"""

    documents_in_queue = serializers.SerializerMethodField()
    title = serializers.CharField(
        required=True,
        error_messages={
            "required": "Поле обязательно для заполнения!",
            "blank": "Поле не может быть пустым!",
        },
    )

    class Meta:
        model = ApprovalQueue
        fields = ["id", "title", "approver", "created_at", "documents_in_queue"]
        validators = [TitleValidator(field="title")]


class QueueItemSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'QueueItem'"""

    class Meta:
        model = QueueItem
        fields = ["position", "queue", "added_at", "document"]
