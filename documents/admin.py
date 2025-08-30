from django.contrib import admin

from documents.models import Folder, Document


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