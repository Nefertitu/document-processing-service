from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.db.models import QuerySet, Count, Q, Case, When, IntegerField
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.html import format_html

from .models import ApprovalQueue, Document, Folder, QueueItem, DocumentFile
from .services import QueueService, DocumentService, get_next_available_admin
from .tasks import send_single_document_email


class DocumentFileInline(admin.TabularInline):
    model = DocumentFile
    extra = 1
    readonly_fields = ["original_name", "uploaded_at", "file_link", "owner"]

    def file_link(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">📄 Открыть</a> | '
                '<a href="{}" download>💾 Скачать</a>',
                obj.file.url,
                obj.file.url
            )
        return "—"

    file_link.short_description = "Действия"


class DocumentInline(admin.TabularInline):
    """Inline для отображения документов внутри папок"""

    model = Document
    extra = 0
    # fields = [
    #     "id",
    #     "title",
    #     "status",
    #     "reviewed_at",
    #     "file",
    #     'file_link'
    #     "review_comment",
    #     "file_answer",
    #     "assigned_admin",
    #     "owner",
    # ]
    # inlines = [DocumentFileInline]
    readonly_fields = [
        "id",
        "title",
        "status",
        "reviewed_at",
        'file_links',
        "get_files_links",
        # 'additional_files_list',
        "review_comment",
        "assigned_admin",
        "owner",
    ]
    can_delete = False
    fieldsets = (
        (None, {
            'fields': (
                "id",
                "title",
                "status",
                "reviewed_at",
                'file_links',
                "get_files_links",
                "review_comment",
                "file_answer",
                "assigned_admin",
                "owner",
            )
        }),
        # ('Дополнительные файлы', {
        #     'fields': ("get_files_links",),
        #     'classes': ('collapse',)
        # }),
        # ('Системная информация', {
        #     'fields': ('file_links',),
        #     'classes': ('collapse',)
    #     }),
    )

    def get_queryset(self, request):
        """
        Получение данных в зависимости от прав.
        Только документы из своих папок (очередей).
        """

        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset

        return queryset.filter(assigned_admin=request.user)

    def file_links(self, obj):
        """Ссылка на основной файл"""

        files = DocumentFile.objects.filter(document=obj.pk)
        file_links = []
        for file in files:
            if file:
                file_links.append(format_html(
                    '<a href="{}" target="_blank" style="font-weight: bold;">📄 ОТКРЫТЬ ОСНОВНОЙ ФАЙЛ</a> | '
                    '<a href="{}" download>💾 Скачать</a>',
                    obj.file.url,
                    obj.file.url
                ))
                return file_links

        return "У файла нет документов"

    file_links.short_description = "Основной файл"


    def get_files_links(self, obj):
        """Отображает все файлы документа (основной + дополнительные)"""
        links = []

        files = DocumentFile.objects.filter(document=obj.id)
        for file in files:
            if file:
                links.append(
                    f'<li><strong>Основной:</strong> '
                    f'<a href="{obj.file.url}" target="_blank">{obj.file.name}</a> '
                    f'<a href="{obj.file.url}" download>💾</a></li>'
                )

    get_files_links.short_description = "Все файлы"
    get_files_links.allow_tags = True

    def review_comment(self, obj):
        """Получить комментарий проверяющего"""
        return obj.document.review_comment

    review_comment.short_description = "Комментарий"

    def has_add_permission(self, request, obj=None):
        """Запрет добавлять элементы вручную"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request, obj=None):
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

    list_filter = (
        "id",
        "title",
    )
    search_fields = (
        "title",
        "created_at",
    )

    inlines = [DocumentInline]

    def get_queryset(self, request):
        """Сохраняем request для использования в других методах"""

        queryset = super().get_queryset(request)

        if request.user.is_authenticated:

            statuses = ["pending", "approved", "rejected", "archived"]
            for status in statuses:
                if request.user.is_superuser:
                    filter_condition = Q(documents__status=status)
                else:
                    filter_condition = Q(documents__status=status) & Q(documents__assigned_admin=request.user)

                queryset = queryset.annotate(
                    **{f"{status}_count": Count("documents", filter=filter_condition)}
                )

        return queryset

    # def has_add_permission(self, request, obj=None):
    #     """Запрет добавлять элементы вручную"""
    #     return False

    def has_delete_permission(self, request, obj=None):
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request, obj=None):
        """Разрешение только на просмотр"""
        return False

    def documents_count(self, obj: Folder) -> int:
        """Добавляет количество документов, где текущий пользователь - ответственный админ"""

        if obj and obj.slug in ["pending", "approved", "rejected", "archived"]:
            return Document.objects.filter(status=obj.slug).count()
        # if obj.slug == "pending" and hasattr(obj, "pending_count"):
        #     return obj.pending_count
        # elif obj.slug == "approved" and hasattr(obj, "approved_count"):
        #     return obj.approved_count
        # elif obj.slug == "rejected" and hasattr(obj, "rejected_count"):
        #     return obj.rejected_count
        # elif obj.slug == "archived" and hasattr(obj, "archived_count"):
        #     return obj.archived_count
        return 0

    # documents_count.short_description = "Количество документов"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Администрирование документов. Позволяет управлять
    документами, с возможностью фильтрации и поиска."""

    actions = ["change_admin_action"]

    list_display = (
        "id",
        "title",
        "status",
        "owner",
        "assigned_admin",
        "owner",
        "uploaded_at",
        "reviewed_at",
        "review_comment",
        "get_reviewed_by",
        "file_answer",
    )

    list_filter = (
        "id",
        "status",
    )
    inlines = [DocumentFileInline]
    search_fields = (
        "title",
        "owner",
        "reviewed_at",
    )
    readonly_fields = [
        "id",
        "title",
        "status",
        "owner",
        "assigned_admin",
        "folder",
        "description",
        "uploaded_at",
        "review_comment",
        "reviewed_by",
        "reviewed_at",
        "file_answer",
    ]
    # fieldsets = (
    #     (None, {
    #         'fields': ('title', 'folder', 'status', 'file')
    #     }),
    #     ('Дополнительные файлы', {
    #         'fields': ('additional_files_list',),
    #         'classes': ('collapse',)
    #     }),
    #     ('Системная информация', {
    #         'fields': ('file_link',),
    #         'classes': ('collapse',)
    #     }),
    # )

    def file_link(self, obj):
        """Ссылка на основной файл"""

        files = DocumentFile.objects.filter(document=obj.id)
        if files:
            links = []
            for file in files:
                links.append(format_html(
                    '<a href="{}" target="_blank" style="font-weight: bold;">📄 ОТКРЫТЬ ОСНОВНОЙ ФАЙЛ</a> | '
                    '<a href="{}" download>💾 Скачать</a>',
                    file.url,
                    file.url
                ))
                return links
        return "У документа нет файлов"

    file_link.short_description = "Файлы документа"

    def has_add_permission(self, request, obj=None):
        """Запрет добавлять элементы вручную"""
        return request.user.is_staff

    def get_queryset(self, request):
        """
        Получение данных в зависимости от прав.
        Только документы из своих папок (очередей).
        """

        queryset = super().get_queryset(request).select_related("reviewed_by")
        if request.user.is_superuser:
            return queryset

        return queryset.filter(assigned_admin=request.user)

    # def has_delete_permission(self, request, obj=None):
    #     """Запрет удаления документов"""
    #     return False

    def get_reviewed_by(self, obj):
        """Добавляет информацию о проверившем администраторе"""
        if obj and obj.reviewed_by:
            return f"{obj.reviewed_by.email} ({obj.reviewed_by.get_full_name()})"
        return "Не проверено"

    get_reviewed_by.short_description = "Проверивший администратор"
    get_reviewed_by.admin_order_field = "reviewed_by__email"

    def has_change_permission(self, request, obj=None):
        """Разрешение на изменение только своих документов или 'superuser'"""

        if obj:
            return request.user.is_superuser or obj.assigned_admin == request.user
        return request.user.is_staff

    def add_view(self, request, form_url="", extra_context=None):
        """Перенаправление при попытке доступа к добавлению"""
        return HttpResponseRedirect(reverse("admin:documents_document_changelist"))

    def get_model_perms(self, request):
        """Скрываем кнопку "Добавить" из интерфейса"""

        perms = super().get_model_perms(request)
        perms["add"] = False
        return perms

    @admin.action(description="Сменить администратора (авто)")
    def change_admin_action(self, request, queryset):
        """
        Изменить администратора для документов.
        Добавить документы выбранному администратору в очередь
        """

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
            self.message_user(request, f"Администратор изменен для {count} документов", messages.SUCCESS)
        else:
            self.message_user(request, "Не удалось изменить администратора", messages.WARNING)


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
    inlines = [DocumentFileInline]
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

    def get_queryset(self, request):
        """Показываем только документы со статусом 'pending'"""

        queryset = super().get_queryset(request)

        user = request.user

        if user.is_superuser:
            return queryset
        return queryset.filter(document__assigned_admin=request.user)


    def get_status(self, obj):
        """Отображает статус документа"""

        document = obj.get_document()
        if document:
            return document.get_status_display()
        return "Документ не найден"

    get_status.short_description = "Статус"

    def get_title(self, obj):
        """Отображает название документа"""

        document = obj.get_document()
        if document and document.title:
            return document.title
        return "Документ не найден"

    get_title.short_description = "Наименование документа"

    def get_all_files_links(self, obj):
        """Отображает все файлы документа в очереди"""
        if not obj.document:
            return "Документ не найден"

        links = []
        document = obj.document
        document_files = document.additional_files.all()

        for doc_file in document_files:
            if doc_file.file:
                try:
                    file_name = doc_file.original_name or doc_file.file.name.split('/')[-1]
                    file_extension = file_name.split('.')[-1].lower() if '.' in file_name else 'file'

                    icon_map = {
                        'pdf': '📄', 'doc': '📝', 'docx': '📝',
                        'xls': '📊', 'xlsx': '📊', 'jpg': '🖼',
                        'jpeg': '🖼', 'png': '🖼', 'zip': '📦', 'rar': '📦'
                    }
                    icon = icon_map.get(file_extension, '📁')

                    link_html = format_html(
                        '<div style="display: flex; gap: 5px; align-items: center; margin-bottom: 8px;">'
                        '<a href="{}" target="_blank" style="background: #417690; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
                        '🔍'
                        '</a>'
                        '<a href="{}" download style="background: #205067; color: white; border: none; padding: 3px 8px; text-decoration: none; border-radius: 3px; display: inline-block; cursor: pointer; font-size: 12px;">'
                        '⬇️'
                        '</a>'
                        '<span style="color: #666; font-size: 13px; margin-left: 5px;">{}</span>'
                        '</div>',
                        doc_file.file.url,
                        doc_file.file.url,
                        file_name
                    )
                    links.append(link_html)
                    print(doc_file.file.url)

                except Exception as e:
                    print(f"Ошибка при обработке файла {doc_file.id}: {e}")
                    continue

        if links:
            combined_html = ''.join(str(link) for link in links)
            return mark_safe(combined_html)
        return "Нет файлов"

    get_all_files_links.short_description = "Все файлы документа"
    get_all_files_links.allow_tags = True

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Кастомный вид полей"""

        if db_field.name == "temp_review_comment":
            kwargs["widget"] = forms.Textarea(
                attrs={
                    "rows": 5,
                    "style": "width: 100%; padding: 8px; border: 2px solid #40E0D0; border-radius: 8px;",
                    "placeholder": "Введите комментарий по итогам проверки...",
                }
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def document_actions(self, obj):
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

    def has_add_permission(self, request, obj=None):
        """Запрет добавлять элементы вручную"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request, obj=None):
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
        "approver",
        "created_at",

    )

    list_filter = (
        "id",
        "approver",
    )
    search_fields = (
        "approver__full_name",
        "title",
    )
    readonly_fields = (
        "created_at",
        "approver",
        "documents_count",
    )

    inlines = [QueueItemInline]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Скрываем стандартные кнопки в админке"""

        extra_context = extra_context or {}
        extra_context["show_save"] = True
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        extra_context["show_close"] = True

        return super().change_view(request, object_id, form_url, extra_context)

    def get_queryset(self, request):
        """Получение данных об очереди в зависимости от прав"""

        queryset = super().get_queryset(request).prefetch_related("items__document")
        user = request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(approver=user)

    def get_urls(self):
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

    def documents_count(self, obj):
        """Возвращает количество документов в очереди текущего администратора"""
        return obj.items.filter(document__status="pending").count()

    documents_count.short_description = "Документов в очереди"

    def status_approval(self, obj):
        """Статус с текстом и иконкой"""

        if obj.is_stop:
            return format_html(
                "<span style='color: red; font-size: 12px;'>❌</span>"
            )
        else:
            return format_html(
                "<span style='color: green; font-size: 12px;'>✅</span>"
            )

    status_approval.short_description = "Действующая очередь"


    def approve_document(self, request, object_id, item_id):
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

    def reject_document(self, request, object_id, item_id):
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

    def save_model(self, request, obj, form, change):
        """Сохранение в документ с помощью кнопки"""

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
                    if 'temp_' in key:
                        print(f"  {key} = {request.POST[key]}")

                print("Все ключи FILES:")
                for key in request.FILES:
                    if 'temp_' in key:
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
                    comment_key = f'items-{i}-temp_review_comment'
                    file_key = f'items-{i}-temp_file_answer'
                    id_key = f'items-{i}-id'

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
                    print(f"Проверка после сохранения:")
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

        if applied:   # Остаемся на странице
            return None

        # return super().save_model(request, obj, form, change)

    def response_change(self, request, obj):
        """Переопределяем редирект после сохранения"""
        if "apply" in request.POST:
            # Остаемся на странице редактирования
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(request.path)

        return super().response_change(request, obj)

    def _handle_queueitem_action(self, request, result: dict):
        """Показ сообщений в админке"""

        if result["success"]:
            messages.success(request, result["message"])
        else:
            messages.error(request, result["message"])

    def has_add_permission(self, request, obj=None):
        """Запрет добавлять элементы вручную"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрет удаления документов"""
        return False

    def has_change_permission(self, request, obj=None):
        """Разрешение только на просмотр текущему администратору"""

        if obj:
            return obj.approver == request.user
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

    def get_queryset(self, request):
        """Показываем только документы со статусом 'pending'"""

        queryset = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(
            document__isnull=False, document__status="pending", document__assigned_admin=request.user
        )

    # def document_file(self, obj):
    #     """Показывает файл из документа"""
    #
    #     return obj.document.file if obj.document else None
    #
    # document_file.short_description = "Файл на согласование"


    def has_add_permission(self, request):
        """Запрещаем добавлять элементы вручную"""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещаем изменять элементы вручную"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрет удаления документов"""
        return False
