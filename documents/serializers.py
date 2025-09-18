import os
from typing import Optional, Any, Dict

from django.conf import settings
from django.db.models import Count
from django.urls import path
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.validators import UniqueValidator

from users.models import User

from .models import ApprovalQueue, Document, DocumentFile, Folder, QueueItem
from .validators import DocumentFileValidator, TitleValidator


class FolderSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'Folder'"""

    documents_in_folder = serializers.SerializerMethodField()
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

    class Meta:
        model = Folder
        fields = (
            "id",
            "title",
            "slug",
            "description",
            "documents_in_folder",
            "created_at",
        )
        read_only_fields = (
            "slug",
            "created_at",
        )
        validators = [TitleValidator(field="title"), DocumentFileValidator()]

    def get_documents_in_folder(self, obj: Folder) -> int:
        """Возвращает аннотированное количество документов для папки"""

        if obj.slug == "pending" and hasattr(obj, "pending_count"):
            return obj.pending_count
        elif obj.slug == "approved" and hasattr(obj, "approved_count"):
            return obj.approved_count
        elif obj.slug == "rejected" and hasattr(obj, "rejected_count"):
            return obj.rejected_count
        elif obj.slug == "archived" and hasattr(obj, "archived_count"):
            return obj.archived_count

        return 0


class BaseDocumentSerializer(serializers.ModelSerializer):
    """Базовый сериализатор с общей логикой"""

    owner_info = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    def get_owner_info(self, obj: Document) -> dict:
        """Возвращает данные о создателе документа"""

        if obj.owner:
            return {
                "email": obj.owner.email,
                "full_name": obj.owner.get_full_name(),
            }

    def get_serializer_context(self) -> Dict[str, Any]:
        """Добавляем request в контекст сериализатора"""

        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_file_url(self, obj: Document) -> str | None:
        """Возвращает абсолютный путь до файла"""

        try:
            document_file = obj.additional_files.first()

            if document_file and document_file.file:
                print(f"file: {document_file}")
                request = self.context.get("request")
                url = document_file.file.url

                if request:
                    return request.build_absolute_uri(url)
                else:
                    if settings.DEBUG:

                        return f"http://localhost:8000{url}"
                    else:
                        return f"https://{os.getenv("SERVER_IP")}{url}"  # ???

        except Exception as e:
            print(f"Ошибка получения URL файла: {e}")

        return None


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
            # "invalid": "Неверный ввод!",
            # "null": "Поле не может быть null!"
        },
    )
    description = serializers.CharField(
        validators=[TitleValidator(field="description")],
        required=False,
        allow_blank=True,
    )
    review_comment = serializers.CharField(
        validators=[TitleValidator(field="description")], required=False, allow_blank=True, read_only=True
    )
    assigned_admin_info = serializers.SerializerMethodField()
    reviewed_by_info = serializers.SerializerMethodField()
    folder = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    show_review_details = serializers.SerializerMethodField()

    def get_assigned_admin_info(self, obj: Document) -> dict | None:
        """Добавляет информацию об ответственном администраторе"""

        if obj.assigned_admin:
            return {"email": obj.assigned_admin.email, "full_name": obj.assigned_admin.get_full_name()}
        return None

    def get_reviewed_by_info(self, obj: Document) -> dict | None:
        """Добавляет информацию о проверившем администраторе"""

        if obj.reviewed_by:
            return {"email": obj.reviewed_by.email, "full_name": obj.reviewed_by.get_full_name()}
        return None

    def get_show_review_details(self, obj: Document) -> str:
        """Определяет, нужно ли показывать детали ревью пользователю"""
        return obj.status in ["approved", "rejected"]

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "description",
            "status",
            "owner_info",
            "assigned_admin_info",
            "uploaded_at",
            "file_url",
            "reviewed_by_info",
            "review_comment",
            "reviewed_at",
            "folder",
            "show_review_details",
        ]
        read_only_fields = [
            "status",
            "uploaded_at",
            "owner_info",
            "assigned_admin_info",
            "reviewed_by_info",
            "folder",
            "review_comment",
            "reviewed_at",
        ]
        validators = [TitleValidator(field="title")]

    def to_representation(self, instance: Document) -> Dict[str, Any]:
        """Переопределяем представление для условного отображения полей"""

        representation = super().to_representation(instance)

        if not self.get_show_review_details(instance):
            representation["review_comment"] = None
            representation["reviewed_at"] = None
            representation["reviewed_by_info"] = None

        return representation

    def update(self, instance, validated_data: Dict[str, Any]) -> Document:
        """Пользователи не могут обновлять документы через этот сериализатор"""
        raise serializers.ValidationError("Пользователи не могут редактировать документы после загрузки")


class DocumentAdminSerializer(BaseDocumentSerializer):
    """
    Сериализатор для администраторов (полные права).
    Могут: видеть все поля и менять статус, reviewer_info.
    Видят: полную информацию о владельце.
    """

    assigned_admin_info = serializers.SerializerMethodField()
    review_comment = serializers.CharField(
        validators=[TitleValidator(field="description")],
    )
    file_url = serializers.SerializerMethodField()

    def get_assigned_admin_info(self, obj: Document) -> dict:
        """Добавляет информацию об администраторе"""

        if obj.assigned_admin:
            return {
                "id": obj.assigned_admin.pk,
                "email": obj.assigned_admin.email,
                "full_name": obj.assigned_admin.get_full_name(),
            }
        return None

    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "description",
            "assigned_admin_info",
            "owner_info",
            "file_url",
            "uploaded_at",
            "reviewed_at",
            "review_comment",
        ]
        read_only_fields = [
            "title",
            "description",
            "assigned_admin_info",
            "owner_info",
            "uploaded_at",
            "reviewed_at",
            "review_comment",
        ]


class ApprovalQueueSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'ApprovalQueue'"""

    count_documents_in_queue = serializers.SerializerMethodField()
    title = serializers.CharField(
        required=True,
        error_messages={
            "required": "Поле обязательно для заполнения!",
            "blank": "Поле не может быть пустым!",
        },
    )
    documents_in_queue = serializers.SerializerMethodField()
    approver_info = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalQueue
        fields = ["id", "title", "approver_info", "created_at", "documents_in_queue", "count_documents_in_queue"]
        validators = [TitleValidator(field="title")]

    def get_count_documents_in_queue(self, obj: ApprovalQueue) -> int:
        """Возвращает количество документов в очереди"""

        request = self.context.get("request")

        if not request or not request.user.is_authenticated:
            return 0

        if request.user.is_superuser:
            return obj.items.count()

        if request.user.is_staff:
            if obj.approver == request.user:
                return obj.items.count()
            return 0

        return obj.items.filter(document__owner=request.user).count()

    def get_documents_in_queue(self, obj: ApprovalQueue) -> dict:
        """Возвращает список документов в очереди"""

        documents_in_queue = Document.objects.filter(queue_items__queue_id=obj.pk)
        for doc in documents_in_queue:
            # file_url = [file.file.url for file in DocumentFile.objects.filter(document=doc.pk)]
            # file_name = [file.file.original_name for file in DocumentFile.objects.filter(document=doc.pk)]

            data = {
                "id": doc.pk,
                "title": doc.title,
                "status": doc.status,
                "uploaded_at": doc.uploaded_at,
                "owner_info": {
                    "owner_email": doc.owner.email,
                    "owner_name": doc.owner.full_name,
                },
                "assigned_admin_info": {
                    "assigned_admin_email": doc.assigned_admin.email,
                    "assigned_admin_name": doc.assigned_admin.full_name,
                },
                "files": [file.file.url for file in DocumentFile.objects.filter(document=doc.pk)],
                # {
                # "file_name": file_name,
                # "file_url": file_url,
                # },
            }
            return data

    def get_approver_info(self, obj: ApprovalQueue) -> dict:
        """Возвращает данные об ответственном администраторе"""

        return {
            "approver_email": obj.approver.email,
            "approver_name": obj.approver.full_name,
        }


class QueueItemSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'QueueItem'"""

    document_title = serializers.SerializerMethodField()
    approval_queue_title = serializers.SerializerMethodField()
    temp_review_comment = serializers.CharField(required=False, allow_blank=True, write_only=True)
    temp_file_answer = serializers.FileField(required=False, write_only=True)

    class Meta:
        model = QueueItem
        fields = [
            "id",
            "document_title",
            "approval_queue_title",
            "position",
            "added_at",
            "temp_review_comment",
            "temp_file_answer",
        ]

    def get_document_title(self, obj: QueueItem) -> str:
        """Возвращает данные о наименовании документа"""
        return obj.document.title

    def get_approval_queue_title(self, obj: QueueItem) -> str:
        """Возвращает название очереди"""
        return obj.queue.title


class DocumentFileSerializer(serializers.ModelSerializer):
    """Сериализатор для модели 'DocumentFile'"""

    class Meta:
        model = DocumentFile
        fields = ["id", "document", "file", "owner", "uploaded_at", "original_name"]
        read_only_fields = ["owner", "uploaded_at", "original_name"]
        validators = [DocumentFileValidator()]

    def create(self, validated_data: dict) -> DocumentFile:
        """Автоматически устанавливается 'owner' и 'original_name'"""

        request = self.context.get("request")
        validated_data["owner"] = request.user
        validated_data["original_name"] = validated_data["file"].name

        return super().create(validated_data)
