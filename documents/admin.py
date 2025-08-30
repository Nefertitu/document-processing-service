from django.contrib import admin
from rest_framework.request import Request
from django.db.models import QuerySet

from documents.models import Folder, Document
from .tasks import send_document_status_email


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    """Администрирование папок. Позволяет управлять
    папками, с возможностью фильтрации и поиска."""

    list_display = (
        "id",
        "title",
        "owner",
        "created_at",
    )

    list_filter = ("id",)
    search_fields = ("title", "owner", "created_at",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Администрирование документов. Позволяет управлять
    документами, с возможностью фильтрации и поиска."""

    @admin.action(description="✅ Подтвердить выбранные документы")
    def approve_documents(modeladmin, request: Request, queryset: QuerySet) -> None:
        """Быстрые действия в Django admin - подтверждение документов"""

        for document in queryset:
            document.status = "approved"
            document.reviewed_by = request.user
            document.save()

            send_document_status_email.delay(
                document_id=document.id,
                status="approved",
                comment=document.review_comment
            )

    @admin.action(description="❌ Отклонить выбранные документы")
    def reject_documents(modeladmin, request: Request, queryset: QuerySet) -> None:
        """Быстрые действия в Django admin - отклонение документов"""

        for document in queryset:
            document.status = "rejected"
            document.reviewed_by = request.user
            document.save()

            send_document_status_email.delay(
                document_id=document.id,
                status="rejected",
                comment=document.review_comment
            )

    list_display = (
        "id",
        # "folder",
        "title",
        "owner",
        "file",
        "status",
        "uploaded_at",
        "reviewed_at",
    )

    list_filter = ("id",)
    search_fields = ("title", "owner", "reviewed_at",)
    # list_display = ['title', 'owner', 'status', 'uploaded_at']
    actions = [approve_documents, reject_documents]

