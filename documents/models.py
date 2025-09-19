import os

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import color
from django.db import models
from django.db.models import Count, Max, Min

from config import settings

from .services import DocumentFilePathGeneratorService, QueueService

User = get_user_model()


class Folder(models.Model):
    """Модель Папка"""

    title = models.CharField(
        max_length=100,
        verbose_name="Название папки",
        default="Мои документы",
        help_text="Заполните название папки",
    )
    slug = models.SlugField(max_length=20, unique=True, verbose_name="Идентификатор")
    description = models.TextField(blank=True, verbose_name="Описание")
    created_at = models.DateTimeField(
        verbose_name="Дата создания",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Папка"
        verbose_name_plural = "Папки"

    def __str__(self) -> str:
        """Строковое отображение модели Папка"""
        return self.title

    @classmethod
    def ensure_system_folders(cls):
        """Создает системные папки если они не существуют"""

        style = color.color_style()

        created_count = 0
        system_folders = [
            {"title": "На рассмотрении", "slug": "pending"},
            {"title": "Одобренные", "slug": "approved"},
            {"title": "Отклоненные", "slug": "rejected"},
            {"title": "Архив", "slug": "archived"},
        ]

        for folder_data in system_folders:
            folder, created = cls.objects.get_or_create(
                slug=folder_data["slug"], defaults={"title": folder_data["title"]}
            )

            if created:
                created_count += 1
                print(style.SUCCESS(f"✅ Создана папка: {folder.title}"))

        if created_count:
            print(style.SUCCESS(f"📁 Создано {created_count} системных папок"))
        else:
            print(style.SUCCESS("📁 Системные папки уже существуют"))


class Document(models.Model):
    """Модель Документ"""

    STATUS_CHOICES = (
        ("pending", "На рассмотрении"),
        ("approved", "Одобрен"),
        ("rejected", "Отклонен"),
        ("archived", "В архиве"),
    )
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_documents",
        verbose_name="Ответственный администратор",
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Наименование документа",
        help_text="Укажите название документа",
    )
    description = models.TextField(
        verbose_name="Описание",
        blank=True,
        help_text="Введите описание документа",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=False,
        null=False,
        verbose_name="Владелец",
        related_name="documents",
    )
    folder = models.ForeignKey(
        "Folder", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Папка", related_name="documents"
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        verbose_name="Статус документа",
        default="pending",
    )
    uploaded_at = models.DateTimeField(
        verbose_name="Дата и время загрузки документа",
        auto_now_add=True,
    )
    reviewed_at = models.DateTimeField(
        verbose_name="Дата и время проверки",
        null=True,
        blank=True,
    )
    review_comment = models.TextField(
        verbose_name="Комментарий при проверке",
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="Проверивший администратор",
        null=True,
        blank=True,
        related_name="reviewed_documents",
    )
    file_answer = models.FileField(
        upload_to=DocumentFilePathGeneratorService.admin_document_path,
        blank=True,
        null=True,
        verbose_name="Ответный файл администратора",
        help_text="Файл для отправки пользователю в качестве ответа",
    )

    class Meta:
        verbose_name = "Документ"
        verbose_name_plural = "Документы"
        ordering = ["-uploaded_at"]

        permissions = [
            ("can_approve_document", "Может подтверждать документы"),
            ("can_reject_document", "Может отклонять документы"),
        ]

    def __str__(self) -> str:
        """Строковое отображение модели Документ"""
        return f"{self.title}"

    def save(self, *args, **kwargs):
        """Создание системных папок"""

        if not self.folder:
            self.folder, created = Folder.objects.get_or_create(slug="pending", defaults={"title": "На рассмотрении"})
        super().save(*args, **kwargs)

    def assign_admin(self, admin=None):
        """Автоматически назначает администратора для документа"""

        if admin:
            # Ручное назначение
            self.assigned_admin = admin
        elif not self.assigned_admin:
            # Автоматическое - ищем администраторов с наименьшей загрузкой
            active_admins = (
                User.objects.filter(is_staff=True, is_active=True, is_superuser=False)
                .annotate(queue_size=Count("approval_queue__items"))
                .order_by("queue_size")
            )
            print(f"active_admins: {active_admins}")

            if active_admins.exists():
                self.assigned_admin = active_admins.first()
            else:
                self.assigned_admin = User.objects.filter(is_superuser=True).first()

        self.save()
        return self.assigned_admin


class DocumentFile(models.Model):
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        related_name="additional_files",
    )
    file = models.FileField(
        verbose_name="Расположение vs название файла",
        upload_to=DocumentFilePathGeneratorService.user_document_path,
        help_text="Загрузите файл",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=False,
        null=False,
        verbose_name="Владелец файла",
        related_name="owner_files",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    original_name = models.CharField(max_length=255)

    def save(self, *args, **kwargs):
        """Определяет способ записи наименования файла"""

        if not self.original_name:
            self.original_name = self.file.name[:20]
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Файл"
        verbose_name_plural = "Файлы"
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        """Строковое отображение модели Файл"""
        return f"{self.file.url}"


class ApprovalQueueManager(models.Manager):
    """Класс менеджер модели 'ApprovalQueue'"""

    def reorganize(self, queue_id):
        """Импорт сервисного метода реорганизации очереди"""
        return QueueService.reorganize_queue(queue_id)


class ApprovalQueue(models.Model):
    """Модель Очередь"""

    title = models.CharField(
        max_length=200,
        verbose_name="Название очереди",
        help_text="Укажите название очереди",
        default="Документы в работе",
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Администратор",
        related_name="approval_queue",
    )
    created_at = models.DateTimeField(
        verbose_name="Время и дата создания очереди",
        auto_now_add=True,
    )
    is_stop = models.BooleanField(
        default=False,
        verbose_name="Остановка очереди",
    )

    objects = ApprovalQueueManager()

    class Meta:
        verbose_name = "Очередь"
        verbose_name_plural = "Очереди"
        ordering = ["approver"]

    def __str__(self) -> str:
        return f"{self.title} ({self.approver.full_name}), документов в очереди: {self.items.all().count()}"

    def get_next_position(self) -> int:
        """Следующая позиция в очереди"""

        max_position = self.items.aggregate(Max("position"))["position__max"]
        print(f"Последняя позиция в очереди: {max_position if max_position else 0}")
        return (max_position or 0) + 1

    # def get_next_document(self):
    #     """Получить следующий документ для обработки"""
    #     return self.items.order_by("position").first()

    def reorganize(self):
        """Пересчитывает позиции элементов в очереди"""
        return self.__class__.objects.reorganize(self.pk)


class QueueItemManager(models.Manager):
    """Модель менеджер очереди"""

    def create_with_position(self, **kwargs):
        """Создает элемент очереди с автоматическим определением позиции"""

        document = kwargs.get("document")
        if not document:
            raise ValueError("Документ не указан")

        queue = QueueService.find_suitable_queue_for_document(document)
        if not queue:
            raise ValueError("Не удалось найти подходящую очередь")

        position = queue.get_next_position()

        item = self.create(queue=queue, document=document, position=position, **kwargs)

        print(f"✅ Документ {document.id} добавлен в очередь: {item.id}")

        return item


class QueueItem(models.Model):
    """Модель Элемент очереди с позицией"""

    queue = models.ForeignKey(
        "ApprovalQueue",
        on_delete=models.CASCADE,
        verbose_name="Очередь",
        related_name="items",  # В ApprovalQueue: approval_queue.items.all()
    )
    document = models.ForeignKey(
        "Document",
        on_delete=models.CASCADE,
        verbose_name="Документ",
        related_name="queue_items",  # document.queue_items.all()
    )
    position = models.PositiveIntegerField(
        verbose_name="№ п/п",
        help_text="Позиция в очереди",
        default=0,
    )
    added_at = models.DateTimeField(
        verbose_name="Добавлен в очередь",
        auto_now_add=True,
    )
    # Временные поля для работы в очереди
    temp_review_comment = models.TextField(
        verbose_name="Черновик комментария",
        blank=True,
    )
    temp_file_answer = models.FileField(
        verbose_name="Черновик файла ответа",
        # upload_to='temp_answers/',
        upload_to=DocumentFilePathGeneratorService.admin_document_path,
        blank=True,
        null=True,
    )

    objects = QueueItemManager()

    def __str__(self) -> str:
        return f"ID: {self.pk} {self.document.title}, (позиция в очереди: {self.position})"

    class Meta:
        verbose_name = "Документ в очереди"
        verbose_name_plural = "Документы в очереди"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["queue", "document"], name="unique_document_in_queue"),
            models.UniqueConstraint(fields=["queue", "position"], name="unique_position_in_queue"),
        ]
        permissions = [
            ("can_review_documents", "Может проверять документы"),
            ("can_upload_answer_file", "Может загружать ответные файлы"),
        ]

    def get_document(self):
        """Безопасное получение документа"""

        try:
            return self.document
        except Document.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        """Сохранение элемента очереди"""

        super().save(*args, **kwargs)

        # if self._state.adding and self.position == 0:
        #     new_position = self.queue.get_next_position()
        #     print(f"Следующая позиция: {new_position}")
        #
        #     print(f"Setting position from {self.position} to {new_position}")
        #     self.position = new_position
        #     super().save(update_fields=["position"])
        #     print(f"QueueItem saved with ID: {self.id}, position: {self.position}")

        # if not QueueItem.objects.filter(queue=queue, document=document).exists():
        #     item = QueueItem.objects.create(
        #         queue=queue,
        #         document=document,
        #         position=ApprovalQueue.get_next_position(queue)
        #     )
        #     print(f"✅ Документ {document.id} добавлен в очередь: {item.id}")
        #     return True

    def delete(self, *args, **kwargs):
        """Переопределяем удаление для автоматической реорганизации очереди"""

        queue = self.queue
        super().delete(*args, **kwargs)
        queue.reorganize()
