import os

from typing import Any, Dict, Optional, List, Union, Callable
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import AdminSite
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Case, Count, IntegerField, Q, QuerySet, When, Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse, URLPattern, URLResolver
from django.utils import timezone
from django.utils.safestring import SafeString
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from documents.utils.file_display import get_file_answer_display, get_files_display_html
from .models import ApprovalQueue, Document, DocumentFile, Folder, QueueItem
from .services import DocumentService, QueueService, get_next_available_admin
from .tasks import send_single_document_email


# class DocumentFileInline(admin.TabularInline):
#     """'InLine' для отображения файлов внутри элементов очереди"""
#     model = DocumentFile
#     extra = 1
#     readonly_fields = ["original_name", "uploaded_at", "file_link", "owner"]


class DocumentInline(admin.TabularInline):
    """Inline для отображения документов внутри папок"""

    model = Document
    extra = 0
    # show_change_link = True

    readonly_fields = [
        "id",
        "title_link",
        "status",
        "assigned_admin",
        "reviewed_at",
    ]
    can_delete = False
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    # "title",
                    "title_link",
                    "status",
                    "assigned_admin",
                    "reviewed_at",
                )
            },
        ),
    )
    list_per_page = 10
    list_max_show_all = 100
    show_full_result_count = True

    def get_queryset(self, request: HttpRequest) -> QuerySet[Document]:
        """
        Получение данных в зависимости от прав.
        Только документы из своих папок (очередей).
        """

        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset

        return queryset.filter(assigned_admin=request.user)

    def title_link(self, obj: Document) -> str:
        """Создает кликабельную ссылку на документ"""

        if obj and obj.id:
            url = reverse("admin:documents_document_change", args=[obj.id])
            return format_html('<a href="{}" style="font-weight: bold;">{}</a>', url, obj.title)
        return obj.title if obj else ""

    title_link.short_description = "Наименование документа"
    title_link.allow_tags = True

    def review_comment(self, obj: Document) -> str:
        """Получить комментарий проверяющего"""
        return obj.document.review_comment

    review_comment.short_description = "Комментарий"

    def has_add_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет добавлять элементы вручную"""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение только на просмотр"""
        return False


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    """Администрирование папок. Позволяет управлять
    папками, с возможностью фильтрации и поиска"""

    list_display = (
        "id",
        "title",
        "created_at",
        "documents_count",
    )

    list_filter = ("title",)
    search_fields = (
        "title",
        "created_at",
    )

    inlines = [DocumentInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Folder]:
        """Сохраняем request для использования в других методах"""

        queryset = super().get_queryset(request)

        if request.user.is_authenticated:

            statuses = ["pending", "approved", "rejected", "archived"]
            for status in statuses:
                if request.user.is_superuser:
                    filter_condition = Q(documents__status=status)
                else:
                    filter_condition = Q(documents__status=status) & Q(documents__assigned_admin=request.user)

                queryset = queryset.annotate(**{f"{status}_count": Count("documents", filter=filter_condition)})

        return queryset

    # def has_add_permission(self, request, obj=None):
    #     """Запрет добавлять элементы вручную"""
    #     return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение только на просмотр"""
        return False

    def documents_count(self, obj: Folder) -> int:
        """Добавляет количество документов, где текущий пользователь - ответственный админ"""

        if obj and obj.slug in ["pending", "approved", "rejected", "archived"]:
            return getattr(obj, f"{obj.slug}_count", 0)
        return 0

    documents_count.short_description = "Количество документов"
    # documents_count.admin_order_field = "pending_count"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Администрирование документов. Позволяет управлять
    документами, с возможностью фильтрации и поиска."""

    actions = ["change_admin_action"]

    list_display = (
        "id",
        "title",
        "status",
        "get_all_files_links",
        "owner",
        "assigned_admin",
        "folder",
        "description",
        "uploaded_at",
        "reviewed_at",
        "review_comment",
        "get_reviewed_by",
        "get_file_answer",
    )

    list_filter = ("status",)
    search_fields = (
        "title",
        "owner",
        "reviewed_at",
    )
    readonly_fields = [
        "id",
        "title",
        "status",
        "get_all_files_links",
        "owner",
        "assigned_admin",
        "folder",
        "description",
        "uploaded_at",
        "get_reviewed_by",
        "reviewed_at",
        "review_comment",
        "get_file_answer",
    ]
    exclude = ["file_answer", "reviewed_by"]
    list_per_page = 10
    list_max_show_all = 100
    show_full_result_count = True
    extra = 0

    def has_add_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет добавлять элементы вручную"""
        return False

    def get_queryset(self, request: HttpRequest) -> QuerySet[Document]:
        """
        Получение данных в зависимости от прав.
        Только документы из своих папок (очередей).
        """

        queryset = super().get_queryset(request).select_related("reviewed_by")
        if request.user.is_superuser:
            return queryset

        return queryset.filter(assigned_admin=request.user)

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет удаления документов"""
        return request.user.is_superuser

    def get_reviewed_by(self, obj: Document) -> str:
        """Добавляет информацию о проверившем администраторе"""

        if obj and obj.reviewed_by:
            return f"{obj.reviewed_by.email} ({obj.reviewed_by.get_full_name()})"
        return "Не проверено"

    get_reviewed_by.short_description = "Проверивший администратор"
    get_reviewed_by.admin_order_field = "reviewed_by__email"

    def get_file_answer(self, obj: Document) -> SafeString | str:
        """Отображает ответный файл документа"""

        if obj.file_answer:
            return get_file_answer_display(obj.file_answer)
        return "Документ отсутствует"

    get_file_answer.short_description = "Ответный файл администратора 📌"
    get_file_answer.allow_tags = True

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение на изменение только своих документов или 'superuser'"""
        return request.user.is_superuser

    def change_view(
        self, request: HttpRequest, object_id: str, form_url: str = "", extra_context: Optional[dict[str, Any]] = None
    ) -> HttpResponse:
        """Скрываем стандартные кнопки в админке"""

        extra_context = extra_context or {}
        extra_context["show_save"] = False
        extra_context["show_delete"] = False
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        extra_context["show_close"] = True

        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(
        self, request: HttpRequest, form_url: str = "", extra_context: Optional[dict[str, Any]] = None
    ) -> HttpResponse:
        """Перенаправление при попытке доступа к добавлению"""
        return HttpResponseRedirect(reverse("admin:documents_document_changelist"))

    def get_model_perms(self, request: HttpRequest) -> dict[str, bool]:
        """Скрываем кнопку "Добавить" из интерфейса"""

        perms = super().get_model_perms(request)
        perms["add"] = False
        return perms

    @admin.action(description="Сменить администратора (авто)")
    def change_admin_action(self, request: HttpRequest, queryset: QuerySet[Document]) -> None:
        """
        Изменить администратора для документов.
        Добавить документы выбранному администратору в очередь
        """

        if not request.user.is_superuser:
            self.message_user(
                request, "❌ Только суперпользователь может менять администратора документов", messages.ERROR
            )
            return

        count = 0
        for document in queryset:
            exclude_admin = document.assigned_admin

            if document.status not in ["approved", "rejected", "archived"]:
                new_admin = get_next_available_admin(exclude_admin=exclude_admin)

                if new_admin:

                    success = DocumentService.move_to_new_queue(document, new_admin)
                    if success:
                        count += 1
                        print(
                            f"Документ {document.title} добавлен в очередь администратора {document.assigned_admin.full_name}"
                        )
                        send_single_document_email.delay(
                            document_id=document.pk, status="pending", comment="Получен новый документ на согласование"
                        )
                    else:
                        print(f"Не удалось переместить документ {document.title}")
            else:
                self.message_user(
                    request, "Нельзя изменить администратора у одобренных и отклоненных документов", messages.ERROR
                )

        if count > 0:
            self.message_user(request, f"✅ Администратор изменен для {count} документов", messages.SUCCESS)
        else:
            self.message_user(request, "⚠️ Не удалось изменить администратора", messages.WARNING)

    def get_actions(self, request: HttpRequest) -> Dict[str, Any]:
        """
        Показывать 'change_admin_action' только суперпользователям
        """

        actions = super().get_actions(request)

        if not request.user.is_superuser:
            if "change_admin_action" in actions:
                del actions["change_admin_action"]

        return actions

    def get_all_files_links(self, obj: Document) -> SafeString:
        """Отображение файлов документа"""
        return get_files_display_html(obj.additional_files.all())

    get_all_files_links.short_description = "Файлы документа на согласование"
    get_all_files_links.allow_tags = True


class QueueItemInline(admin.TabularInline):
    """Inline для отображения элементов очереди внутри очереди"""

    model = QueueItem
    extra = 0
    fields = (
        "id",
        "position",
        "get_status",
        "get_title",
        "added_at",
        "get_all_files_links",
        "temp_review_comment",
        "temp_file_answer",
        "document_actions",
    )
    # inlines = [DocumentFileInline]
    readonly_fields = [
        "id",
        "position",
        "get_status",
        "get_title",
        "added_at",
        "get_all_files_links",
        "document_actions",
    ]
    can_delete = False

    list_per_page = 10
    list_max_show_all = 100
    show_full_result_count = True

    def get_queryset(self, request: HttpRequest) -> QuerySet[QueueItem]:
        """Показываем только документы со статусом 'pending'"""

        queryset = super().get_queryset(request)

        user = request.user

        if user.is_superuser:
            return queryset
        return queryset.filter(document__assigned_admin=request.user)

    def get_status(self, obj: QueueItem) -> str:
        """Отображает статус документа"""

        document = obj.get_document()
        if document:
            return document.get_status_display()
        return "Документ не найден"

    get_status.short_description = "Статус"

    def get_title(self, obj: QueueItem) -> str:
        """Отображает название документа"""

        document = obj.get_document()
        if document and document.title:
            return document.title
        return "Документ не найден"

    get_title.short_description = "Наименование документа"

    def get_all_files_links(self, obj: QueueItem) -> SafeString | str:
        """Отображает все файлы документа в очереди"""

        if not obj.document:
            return "Документ не найден"
        return get_files_display_html(obj.document.additional_files.all())

    get_all_files_links.short_description = "Все файлы документа"
    get_all_files_links.allow_tags = True

    def formfield_for_dbfield(self, db_field: models.Field, request: HttpRequest, **kwargs: Any) -> forms.Field:
        """Кастомный вид полей"""

        if db_field.name == "temp_review_comment":
            kwargs["widget"] = forms.Textarea(
                attrs={
                    "rows": 5,
                    "style": "width: 98%; padding: 6px; border: 2px solid #40E0D0; border-radius: 8px;",
                    "placeholder": "Введите комментарий по итогам проверки...",
                }
            )

        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def document_actions(self, obj: QueueItem) -> SafeString:
        """Кнопки действий с переносом данных"""

        if not obj.document:
            return "Документ не найден"

        return format_html(
            """
            <div style="display: flex; gap: 10px; flex-direction: column;">
                <button type="submit" name="apply" value="{}" style="background: #417690; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
                    💾 Сохранить в документ
                </button>
                <div style="display: flex; gap: 10px;">
                <a href="../queueitem/{}/approve/" style="background: #2E7D32; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        ✅ Одобрить
                    </a>
                    <a href="../queueitem/{}/reject/" style="background: #205067; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        ❌ Отклонить
                    </a>
                </div>
            </div>
            """,
            obj.id,
            obj.id,
            obj.id,
        )

    document_actions.short_description = "Действия"

    def get_readonly_fields(self, request: HttpRequest, obj: Optional[Model] = None) -> List[Union[str, Callable]]:
        """Определяем какие поля доступны для редактирования"""

        print(f"🔍 User: {request.user}")
        print(f"🔍 Superuser: {request.user.is_superuser}")
        print(f"🔍 Can approve: {request.user.has_perm('documents.can_approve_document')}")
        print(f"🔍 Can reject: {request.user.has_perm('documents.can_reject_document')}")

        base_readonly = [
            "id",
            "position",
            "get_status",
            "get_title",
            "added_at",
            "get_all_files_links",
            "document_actions",
        ]

        if request.user.is_superuser:
            return base_readonly

        if request.user.has_perm("documents.can_approve_document") and request.user.has_perm(
            "documents.can_reject_document"
        ):
            return base_readonly

        return base_readonly + ["temp_review_comment", "temp_file_answer"]

    def has_add_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет добавлять элементы вручную"""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение только на просмотр и частичное изменение"""
        return True


@admin.register(ApprovalQueue)
class ApprovalQueueAdmin(admin.ModelAdmin):
    """
    Создание очереди документов администратора.
    Позволяет управлять очередями.
    """

    list_display = (
        "id",
        "title",
        "documents_count",
        "status_approval",
        "approver_info",
        "created_at",
    )

    list_filter = ("approver",)
    search_fields = (
        "approver__full_name",
        "title",
    )
    readonly_fields = ("documents_count", "approver_info")
    exclude = ["approver"]

    inlines = [QueueItemInline]

    def change_view(
        self, request: HttpRequest, object_id: str, form_url: str = "", extra_context: Optional[dict[str, Any]] = None
    ) -> HttpResponse:
        """Настройка отображения для редактирования существующей очереди"""

        extra_context = extra_context or {}
        extra_context["show_delete"] = False
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        extra_context["show_save"] = False
        extra_context["show_close"] = True

        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(
        self, request: HttpRequest, form_url: str = "", extra_context: Optional[dict[str, Any]] = None
    ) -> HttpResponse:
        """Настройка отображения для создания новой очереди"""

        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = True
        extra_context["show_save_and_add_another"] = True
        extra_context["show_save"] = True
        extra_context["show_close"] = True
        return super().add_view(request, form_url, extra_context)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ApprovalQueue]:
        """Получение данных об очереди в зависимости от прав"""

        queryset = super().get_queryset(request).prefetch_related("items__document")
        user = request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(approver=user)

    def approver_info(self, obj: ApprovalQueue) -> str:
        """Кастомное отображение 'approver'"""
        if obj.approver:
            return f"{obj.approver.get_full_name()} \n({obj.approver.email})"

    approver_info.short_description = "Ответственный администратор"

    def get_urls(self) -> List[Union[URLPattern, URLResolver]]:
        """Добавляем кастомные URLs для действий"""

        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/queueitem/<int:item_id>/approve/",
                self.admin_site.admin_view(self.approve_document),
                name="document_approve_queueitem",
            ),
            path(
                "<path:object_id>/queueitem/<int:item_id>/reject/",
                self.admin_site.admin_view(self.reject_document),
                name="document_reject_queueitem",
            ),
        ]
        print("DEBUG: Custom URLs registered:")
        for url in custom_urls:
            print(f"  {url.pattern} -> {url.name}")
        return custom_urls + urls

    def documents_count(self, obj: ApprovalQueue) -> int:
        """Возвращает количество документов в очереди текущего администратора"""
        return obj.items.filter(document__status="pending").count()

    documents_count.short_description = "Документов в очереди"

    def status_approval(self, obj: ApprovalQueue) -> SafeString:
        """Статус с текстом и иконкой"""

        if obj.is_stop:
            return format_html("<span style='color: red; font-size: 12px;'>❌</span>")
        else:
            return format_html("<span style='color: green; font-size: 12px;'>✅</span>")

    status_approval.short_description = "Действующая очередь"

    def approve_document(self, request: HttpRequest, object_id: str, item_id: str) -> HttpResponse:
        """Одобрение документа из админки"""

        print(f"🟢 APPROVE: object_id={object_id}, item_id={item_id}")
        result = DocumentService.handle_queue_action(item_id, request.user, "approve")
        print(f"Результат: {result}")
        if result["success"]:
            try:
                document = Document.objects.get(id=result.get("document_id"))
                document.reviewed_at = timezone.localtime()
                document.save()
            except Document.DoesNotExist:
                pass

        self._handle_queueitem_action(request, result)
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/admin/"))

    def reject_document(self, request: HttpRequest, object_id: str, item_id: str) -> HttpResponse:
        """Отклонение документа из админки"""

        print(f"🔴 REJECT: object_id={object_id}, item_id={item_id}")
        result = DocumentService.handle_queue_action(item_id, request.user, "reject")
        if result["success"]:
            try:
                document = Document.objects.get(id=result.get("document_id"))
                document.reviewed_at = timezone.localtime()
                document.save()
            except Document.DoesNotExist:
                pass

        self._handle_queueitem_action(request, result)
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/admin/"))

    def save_model(self, request: HttpRequest, obj: ApprovalQueue, form: forms.ModelForm, change: bool) -> None:
        """Сохранение в документ с помощью кнопки"""

        if not change:
            obj.approver = request.user

        super().save_model(request, obj, form, change)

        applied = False

        if "apply" in request.POST:
            queue_item_id = request.POST["apply"]
            if isinstance(queue_item_id, list):
                queue_item_id = queue_item_id[0]

            print(f"Ищем QueueItem с ID: {queue_item_id}")

            try:
                queue_item = QueueItem.objects.get(id=queue_item_id)
                print(f"Найден QueueItem: {queue_item.id}, Документ: {queue_item.document.id}")

                # ОТЛАДКА: выведем все ключи
                print("Все ключи POST:")
                for key in request.POST:
                    if "temp_" in key:
                        print(f"  {key} = {request.POST[key]}")

                print("Все ключи FILES:")
                for key in request.FILES:
                    if "temp_" in key:
                        print(f"  {key} = {request.FILES[key].name}")

                temp_comment = None
                temp_file = None

                # Ищем комментарий
                for key in request.POST:
                    if key.endswith("-temp_review_comment") and queue_item_id in key:
                        temp_comment = request.POST[key]
                        if isinstance(temp_comment, list):
                            temp_comment = temp_comment[0]
                        print(f"Найден комментарий: {temp_comment}")

                # Ищем файл в FILES
                for i in range(10):  # Проверяем первые 10 индексов
                    comment_key = f"items-{i}-temp_review_comment"
                    file_key = f"items-{i}-temp_file_answer"
                    id_key = f"items-{i}-id"

                    # Проверяем что это наш элемент
                    if id_key in request.POST and request.POST[id_key] == str(queue_item_id):
                        if comment_key in request.POST:
                            temp_comment = request.POST[comment_key]
                            if isinstance(temp_comment, list):
                                temp_comment = temp_comment[0]
                            print(f"Найден комментарий для индекса {i}: {temp_comment}")

                        if file_key in request.FILES and request.FILES[file_key]:
                            temp_file = request.FILES[file_key]
                            print(f"Найден файл: {temp_file.name} ({temp_file.size} bytes)")
                        else:
                            print(f"Файл не загружен или пустой для ключа: {file_key}")
                        break
                # Сохраняем в документ
                if queue_item.document:
                    document = queue_item.document
                    if temp_comment:
                        document.review_comment = temp_comment
                        print(f"Установлен комментарий': {temp_comment}")

                    if temp_file:
                        document.file_answer = temp_file
                        print(f"Загружен файл: {temp_file.name}")

                    document.save()
                    print("Проверка после сохранения:")
                    print(f"Комментарий документа: '{document.review_comment}'")
                    print(f"Файл документа: {document.file_answer}")
                    print(f"Файл существует: {document.file_answer.name if document.file_answer else 'No'}")

                    messages.success(request, f"Данные сохранены в документ c ID: {queue_item.document.id}")
                    applied = True
                else:
                    messages.error(request, "Документ не найден")

            except QueueItem.DoesNotExist:
                print(f"QueueItem {queue_item_id} not found")
                messages.error(request, f"Элемент очереди с ID {queue_item_id} не найден")

        if applied:  # Остаемся на странице
            return None

    def response_change(self, request, obj):
        """Переопределяем редирект после сохранения"""

        if "apply" in request.POST:
            from django.http import HttpResponseRedirect

            return HttpResponseRedirect(request.path)

        return super().response_change(request, obj)

    def _handle_queueitem_action(self, request: HttpRequest, result: dict) -> None:
        """Показ сообщений в админке"""

        if result["success"]:
            messages.success(request, result["message"])
        else:
            messages.error(request, result["message"])

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение удаления очереди"""
        return True

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Разрешение только на просмотр текущему администратору"""

        if obj:
            return obj.approver == request.user
        return True

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Разрешение добавлять элементы вручную"""
        return True


@admin.register(QueueItem)
class QueueItemAdmin(admin.ModelAdmin):
    """
    Администрирование документов в очереди.
    Только для просмотра, без изменений.
    """

    list_display = (
        "id",
        "position",
        "queue",
        "document",
        "added_at",
        # "document_file",
        "temp_review_comment",
        "temp_file_answer",
    )

    readonly_fields = (
        "queue",
        "document",
        "position",
        "added_at",
        # "document_file",
        "temp_review_comment",
        "temp_file_answer",
    )

    list_per_page = 10
    list_max_show_all = 100
    show_full_result_count = True
    extra = 0

    class Media:
        css = {"all": ("/static/admin/css/custom.css",)}

    def get_queryset(self, request: HttpRequest) -> QuerySet[QueueItem]:
        """Показываем только документы со статусом 'pending'"""

        queryset = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(
            document__isnull=False, document__status="pending", document__assigned_admin=request.user
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Запрещаем добавлять элементы вручную"""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрещаем изменять элементы вручную"""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Model] = None) -> bool:
        """Запрет удаления документов"""
        return False
