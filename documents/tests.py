import io
import os
from datetime import datetime, time, timedelta
from io import StringIO
from unittest import mock
from unittest.mock import patch

from django.contrib import admin, messages
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponseRedirect
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APITestCase

from config import settings
from users.models import User

from .admin import ApprovalQueueAdmin, DocumentAdmin
from .models import ApprovalQueue, Document, DocumentFile, Folder, QueueItem
from .services import DocumentHeavyProcessingService, DocumentService, setup_task_archive_old_documents
from .tasks import archive_old_documents, optimize_image_task, send_single_document_email


class DocumentTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'Document'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document",
        )

        Folder.ensure_system_folders()

        self.mock_file = SimpleUploadedFile(
            "test_image.jpg", b"file_content", content_type="image/jpeg"  # Бинарное содержимое файла
        )

        self.client.force_authenticate(user=self.user)
        print(
            f"📄 Создан документ ID: {self.document.pk}, Title: {self.document.title}, Status: {self.document.status}"
        )

    def test_document_retrieve(self) -> None:
        """Тест получения деталей документа"""

        url = reverse("documents:document-detail", kwargs={"pk": self.document.pk})
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data

        self.assertEqual(data.get("id"), self.document.pk)
        self.assertEqual(data.get("title"), self.document.title)
        self.assertEqual(data.get("owner_info")["email"], self.document.owner.email)
        self.assertEqual(data.get("owner_info")["full_name"], self.document.owner.full_name)
        self.assertEqual(data.get("assigned_admin_info")["email"], self.admin.email)
        self.assertEqual(data.get("assigned_admin_info")["full_name"], self.admin.full_name)
        self.assertEqual(data.get("status"), "pending")
        self.assertEqual(data.get("folder"), "pending")

    def test_document_create(self):
        """Тест создания документа"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {
            "title": "Test 2 from 2",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "files": self.mock_file,
        }

        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Document.objects.filter(title="Test 2 from 2").exists())
        self.assertEqual(response.data["data"]["owner_info"]["email"], self.user.email)
        self.assertEqual(response.data["data"]["assigned_admin_info"]["email"], self.admin.email)
        self.assertEqual(response.data["data"]["status"], "pending")

    def test_document_access(self):
        """Тест проверяет доступ к документу разными пользователями"""

        # Проверяем доступ владельца
        self.client.force_authenticate(user=self.user)
        url = reverse("documents:document-detail", kwargs={"pk": self.document.pk})
        response = self.client.get(url)
        print(f"👤 Владелец - Status: {response.status_code}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Проверяем доступ админа
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(url)
        print(f"👨‍💼 Админ - Status: {response.status_code}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Проверяем доступ неавторизованного пользователя
        self.client.logout()
        response = self.client.get(url)
        print(f"👻 Аноним - Status: {response.status_code}")

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        if self.client._credentials:
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        else:
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_documents_list(self) -> None:
        """Тест списка документов"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")
        response = self.client.get(url)
        data = response.json()
        print(f"data999 список: {data}")

        document = self.document

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(Document.objects.all().count(), 1)
        self.assertEqual(len(data["results"]), 1)

        documents_data = data["results"][0]
        self.assertEqual(documents_data["id"], document.pk)
        self.assertEqual(documents_data["owner_info"]["email"], self.user.email)
        self.assertEqual(documents_data["status"], self.document.status)
        self.assertEqual(documents_data["title"], self.document.title)

    def test_document_delete(self) -> None:
        """Тест удаления документа"""

        self.client.force_authenticate(user=self.superuser)

        url = reverse("documents:document-detail", args=(self.document.pk,))

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(Document.DoesNotExist):
            Document.objects.get(pk=self.document.pk)

    @parameterized.expand(
        [
            ("", "Поле не может быть пустым!"),
            ("криптовалюта", "Нельзя использовать запрещенные слова (криптовалюта) в названии и/или описании!"),
            ("123", "Название должно содержать хотя бы одну букву!"),
            ("VS", "Название должно содержать минимум 3 символа!"),
            (
                "/*/",
                "Название может состоять из русских и английских букв, цифр, пробелов, дефисов (-) и подчеркиваний (_)!",
            ),
        ]
    )
    def test_documents_create_invalid_title(self, invalid_value, expected_error) -> None:
        """Тест создания документа с невалидным полем 'title'"""

        url = reverse("documents:document-list")
        invalid_data = {
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "title": invalid_value,
        }
        response = self.client.post(url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error, response.data["error"])

    def test_document_creation_with_large_file(self) -> None:
        """Тест проверки работы валидации размера загружаемого с документом файла"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        large_file = SimpleUploadedFile("large_image.jpg", b"0" * (5 * 1024 * 1024), content_type="image/jpeg")

        data = {
            "title": "New Document with large file",
            "files": large_file,
            "owner": self.user.pk,
            "assigned_admin": self.admin.id,
        }

        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        error_message = str(response.data)

        self.assertIn("Файл", error_message)
        self.assertIn("слишком большой", error_message)
        self.assertIn("5.0", error_message)
        self.assertIn("4.0", error_message)
        self.assertIn("MB", error_message)


class ApprovalQueueTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'ApprovalQueue'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(ApprovalQueue)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )

        # Назначаем права пользователю
        self.admin.user_permissions.add(approve_perm)
        self.admin.save()

        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document",
        )
        self.approvalqueue = ApprovalQueue.objects.create(
            title="New Test Approval",
            approver=self.admin,
        )
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )
        print(f"Создана очередь {self.approvalqueue}")

        Folder.ensure_system_folders()

        self.mock_file = SimpleUploadedFile(
            "test_image.jpg", b"file_content", content_type="image/jpeg"  # Бинарное содержимое файла
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document,
            file=self.mock_file,
            owner=self.user,
            original_name="test_image.jpg",
        )

        self.client.force_authenticate(user=self.admin)
        print(f"📄 Создана Очередь: {self.approvalqueue.approver}")

    def test_approval_queue_retrieve(self) -> None:
        """Тест получения деталей очереди"""

        self.assertTrue(ApprovalQueue.objects.filter(pk=self.approvalqueue.pk).exists())
        print(f"✅ Эта Очередь существует: {self.approvalqueue.pk}")

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:approvalqueue-detail", kwargs={"pk": self.approvalqueue.pk})

        response = self.client.get(url)
        data = response.data

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(data.get("title"), self.approvalqueue.title)
        self.assertEqual(data["approver_info"]["approver_email"], self.admin.email)
        self.assertEqual(data.get("count_documents_in_queue"), 1)
        documents_count = self.approvalqueue.items.all().count()
        self.assertEqual(data.get("count_documents_in_queue"), documents_count)
        self.assertFalse(data.get("is_stop"))

    def test_document_creation_creates_approval_queue(self):
        """Тест, что создание документа автоматически включает его в очередь"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {
            "title": "Test document for approval queue test",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "files": self.mock_file,
        }

        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        document_id = response.data["data"]["id"]
        queue_item_exists = QueueItem.objects.filter(document_id=document_id).exists()
        self.assertTrue(queue_item_exists)

        queue_item = QueueItem.objects.get(document=document_id)
        self.assertEqual(queue_item.queue.approver, self.admin)
        self.assertEqual(queue_item.document.status, "pending")

        queue = ApprovalQueue.objects.get(title="New Test Approval")
        total_documents = queue.items.count()
        self.assertEqual(queue_item.position, total_documents)
        self.assertEqual(queue_item.position, 2)

    def test_approval_queue_delete(self) -> None:
        """Тест удаления очереди"""

        self.client.force_authenticate(user=self.superuser)

        document_id = self.document_file.document.pk
        queue_item_id = QueueItem.objects.get(document=document_id).pk
        approval_queue_items = self.approvalqueue.items.all()
        approval_queue_item_id = [approval_queue_item.pk for approval_queue_item in approval_queue_items][0]
        self.assertEqual(queue_item_id, approval_queue_item_id)

        url = reverse("documents:document-detail", args=(document_id,))
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(Document.DoesNotExist):
            Document.objects.get(pk=document_id)

        approval_queue_id = self.approvalqueue.pk

        url = reverse("documents:approvalqueue-detail", args=(approval_queue_id,))
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(ApprovalQueue.DoesNotExist):
            ApprovalQueue.objects.get(pk=approval_queue_id)

    def test_approval_queue_with_doc_delete_error(self) -> None:
        """Тест ошибки удаления очереди с документом"""

        self.client.force_authenticate(user=self.superuser)

        url = reverse("documents:approvalqueue-detail", args=(self.approvalqueue.pk,))
        response = self.client.delete(url)
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", data)
        self.assertIn("нельзя удалить очередь с документами", data["error"].lower())

    def test_approval_queue_delete_admin_error(self) -> None:
        """
        Тест ошибки удаления очереди без документа админом
        (право удаления очереди имеет только суперпользователь)
        """

        self.client.force_authenticate(user=self.superuser)

        document_id = self.document_file.document.pk
        queue_item_id = QueueItem.objects.get(document=document_id).pk
        approval_queue_items = self.approvalqueue.items.all()
        approval_queue_item_id = [approval_queue_item.pk for approval_queue_item in approval_queue_items][0]
        self.assertEqual(queue_item_id, approval_queue_item_id)

        url = reverse("documents:document-detail", args=(document_id,))
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(Document.DoesNotExist):
            Document.objects.get(pk=document_id)

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:approvalqueue-detail", args=(self.approvalqueue.pk,))
        response = self.client.delete(url)
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("error", data)
        self.assertIn("у вас нет прав для удаления очереди", data["error"].lower())


class QueueItemTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'QueueItem'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )
        view_all_perm, created = Permission.objects.get_or_create(
            codename="view_all_documents", content_type=content_type, defaults={"name": "Can view all documents"}
        )

        # Назначаем права пользователю
        self.admin.user_permissions.add(approve_perm, reject_perm, view_all_perm)
        self.admin.save()

        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document",
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )
        print(f"Создан элемент очереди {self.queue_item}")

        Folder.ensure_system_folders()

        self.mock_file = SimpleUploadedFile(
            "test_image.jpg", b"file_content", content_type="image/jpeg"  # Бинарное содержимое файла
        )

        self.client.force_authenticate(user=self.user)
        print(
            f"📄 Создан документ ID: {self.document.pk}, Очередь: {self.approvalqueue.approver}, QueueItem: {self.queue_item.position}"
        )

    def test_queue_item_retrieve(self) -> None:
        """Тест получения деталей элемента очереди"""

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:queueitem-detail", kwargs={"pk": self.queue_item.pk})

        response = self.client.get(url)
        data = response.data

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data.get("approval_queue_title"), self.queue_item.queue.title)
        self.assertEqual(data.get("document_title"), self.queue_item.document.title)
        self.assertEqual(data.get("position"), 1)

    def test_document_creation_creates_queue_item(self):
        """Тест, что создание документа автоматически создает элемент очереди"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {
            "title": "Test document for queue_item test",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "files": self.mock_file,
        }
        print(f"📋 Request data keys: {list(data.keys())}")
        print(f"📋 File type: {type(self.mock_file)}")

        response = self.client.post(url, data, format="multipart")
        print(f"📊 Response status: {response.status_code}")
        print(f"📊 Response data: {response.data}")

        if response.status_code != status.HTTP_201_CREATED:
            self.fail(f"Document creation failed with 400: {response.data}")

        data = response.json()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        document_id = response.data["data"]["id"]
        queue_item_exists = QueueItem.objects.filter(document_id=document_id).exists()
        self.assertTrue(queue_item_exists)

    def test_queue_item_list(self) -> None:
        """Тест списка файлов"""

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:queueitem-list")

        response = self.client.get(url)
        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        queue_items = QueueItem.objects.all()
        self.assertEqual(queue_items.count(), 1)

        queue_items_data = data["results"][0]
        self.assertEqual(queue_items_data["position"], self.queue_item.position)
        self.assertEqual(queue_items_data["approval_queue_title"], self.queue_item.queue.title)
        self.assertEqual(queue_items_data["document_title"], self.queue_item.document.title)

    def test_documents_approval(self) -> None:
        """Тест одобрения документа через 'QueueItem'"""

        self.client.force_authenticate(user=self.admin)

        document_id = self.document.pk
        queue_item = self.queue_item

        self.assertTrue(document_id, queue_item.document.pk)

        url = reverse("documents:queueitem-approve", kwargs={"pk": self.queue_item.pk})
        data = {
            "status": "approved",
        }
        response = self.client.post(url, data, format="multipart")

        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.document.refresh_from_db()

        self.assertEqual(self.document.status, "approved")
        self.assertTrue(queue_item.document.pk, None)
        self.assertEqual(self.document.reviewed_by, self.admin)

        with self.assertRaises(QueueItem.DoesNotExist):
            QueueItem.objects.get(pk=self.queue_item.pk)

    def test_documents_update(self) -> None:
        """
        Тест добавления комментария и/или ответного файла
        в документ через 'QueueItem'
        """

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:queueitem-detail", kwargs={"pk": self.queue_item.pk})
        data = {
            "temp_review_comment": "Agreed!",
            "temp_file_answer": self.mock_file,
        }
        response = self.client.patch(url, data, format="multipart")

        data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.document.refresh_from_db()

        self.assertEqual(self.document.review_comment, "Agreed!")

        if hasattr(self.document, "file_answer"):
            self.assertTrue(self.document.file_answer)

    def test_documents_rejected(self) -> None:
        """Тест одобрения документа через 'QueueItem'"""

        self.client.force_authenticate(user=self.admin)

        document_id = self.document.pk
        queue_item = self.queue_item

        self.assertTrue(document_id, queue_item.document.pk)

        url = reverse("documents:queueitem-reject", kwargs={"pk": self.queue_item.pk})
        data = {
            "status": "rejected",
        }
        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.document.refresh_from_db()

        self.assertEqual(self.document.status, "rejected")
        self.assertTrue(queue_item.document.pk, None)
        self.assertEqual(self.document.reviewed_by, self.admin)


class DocumentFileTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'DocumentFile'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_image.jpg"
        )

        Folder.ensure_system_folders()

        self.client.force_authenticate(user=self.user)

    def test_document_file_retrieve(self) -> None:
        """Тест получения деталей фалов документа"""

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:documentfile-detail", kwargs={"pk": self.document_file.pk})

        response = self.client.get(url)
        data = response.data
        print(f"Data DocumentFile: {data}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(data.get("document"), self.document_file.document.pk)
        self.assertEqual(data.get("owner"), self.user.pk)

    def test_document_file_list(self) -> None:
        """Тест получения списка файлов"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:documentfile-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_document_creation_with_files(self) -> None:
        """Тест, подтверждающий, что при создании документа файлы тоже создаются"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {"title": "New Document with File", "files": self.mock_file, "assigned_admin": self.admin.id}

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        document_id = response.data["data"]["id"]
        file_exists = DocumentFile.objects.filter(document_id=document_id).exists()
        self.assertTrue(file_exists)

    def test_document_files_list(self) -> None:
        """Тест списка файлов"""

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:documentfile-list")
        response = self.client.get(url)
        data = response.json()

        document_file = self.document_file.file

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(Document.objects.all().count(), 1)

        documents_files_data = data[0]
        self.assertEqual(documents_files_data["original_name"], self.document_file.original_name)
        self.assertEqual(documents_files_data["owner"], self.user.pk)
        self.assertEqual(documents_files_data["document"], self.document.pk)
        self.assertTrue(document_file.file)

    def test_document_file_delete(self) -> None:
        """Тест удаления документа"""

        self.client.force_authenticate(user=self.superuser)

        url = reverse("documents:documentfile-detail", args=(self.document_file.pk,))

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(DocumentFile.DoesNotExist):
            DocumentFile.objects.get(pk=self.document_file.pk)


class SendInformationTaskTest(APITestCase):
    """Тест кейс для проверки выполнения задачи по отправке сообщения"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.large_file = SimpleUploadedFile("large_image.jpg", b"0" * (5 * 1024 * 1024), content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.large_file, owner=self.user, original_name="test_large_image.jpg"
        )

        Folder.ensure_system_folders()

        self.client.force_authenticate(user=self.user)

    @patch("documents.tasks.send_mail")
    def test_send_information_success(self, mock_send_mail):
        """
        Тест успешной отправки сообщения о получении
        документа на согласование на 'email' админу
        """

        send_single_document_email(document_id=self.document.pk, status=self.document.status, comment="")

        mock_send_mail.assert_called_once_with(
            subject="Получен документ на согласование",
            message=f"Документ '{self.document.title}' создан {self.document.uploaded_at}, ожидает подтверждения.",
            from_email=os.getenv("EMAIL_HOST_USER"),
            recipient_list=[self.admin.email],
            fail_silently=False,
        )

        args, kwargs = mock_send_mail.call_args

        self.assertEqual(kwargs.get("subject"), "Получен документ на согласование")

        message = kwargs.get("message", "")
        self.assertIn(f"Документ '{self.document.title}' создан", message)
        self.assertIn("ожидает подтверждения", message)
        self.assertIn(str(self.document.uploaded_at.year), message)

        self.assertEqual(kwargs.get("from_email"), os.getenv("EMAIL_HOST_USER"))
        self.assertEqual(kwargs.get("recipient_list"), [self.admin.email])

    @patch("documents.tasks.EmailMessage")
    def test_send_information_success_status_approved(self, mock_email_message):
        """
        Тест успешной отправки сообщения о получении
        документом статуса одобренного на 'email' пользователю
        """

        send_single_document_email(document_id=self.document.pk, status="approved", comment="")

        mock_email_message.assert_called_once_with(
            subject="✅ Ваш документ подтвержден!",
            body=f"Документ '{self.document.title}' был подтвержден.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[self.user.email],
        )

        args, kwargs = mock_email_message.call_args

        self.assertEqual(kwargs.get("subject"), "✅ Ваш документ подтвержден!")

        message = kwargs.get("body", "")
        self.assertIn(f"Документ '{self.document.title}' был подтвержден.", message)
        self.assertEqual(kwargs.get("from_email"), settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(kwargs.get("to"), [self.user.email])

    @patch("documents.tasks.EmailMessage")
    def test_send_information_success_status_rejected(self, mock_email_message):
        """
        Тест отправки сообщения о получении
        документом статуса 'отклонен' на 'email' пользователю
        """

        send_single_document_email(document_id=self.document.pk, status="rejected", comment="")

        mock_email_message.assert_called_once_with(
            subject="❌ Ваш документ отклонен!",
            body=f"Документ '{self.document.title}' был отклонен.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[self.user.email],
        )

        args, kwargs = mock_email_message.call_args

        self.assertEqual(kwargs.get("subject"), "❌ Ваш документ отклонен!")

        message = kwargs.get("body", "")
        self.assertIn(f"Документ '{self.document.title}' был отклонен.", message)
        self.assertEqual(kwargs.get("from_email"), settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(kwargs.get("to"), [self.user.email])

    @patch("documents.tasks.send_single_document_email.delay")
    def test_task_send_email_delay_called(self, mock_delay):
        """Тест успешного вызова задачи отправки сообщения"""

        send_single_document_email.delay(
            document_id=self.document.pk,
            status=self.document.status,
            comment="",
        )

        mock_delay.assert_called_once_with(
            document_id=self.document.pk,
            status=self.document.status,
            comment="",
        )

    @patch("documents.tasks.optimize_image_task.delay")
    def test_task_optimize_delay_called(self, mock_optimize_image):
        """Тест успешного вызова задачи по оптимизации 'jpeg' файла"""

        result = optimize_image_task.delay(
            document_id=self.document_file.pk,
        )

        print(f"result: {result}")

        mock_optimize_image.assert_called_once_with(
            document_id=self.document_file.pk,
        )


class DocumentHeavyProcessingServiceTest(APITestCase):
    """Тест кейс для проверки работы сервиса тяжелых операций с файлами"""

    def setUp(self):
        """Подготовка данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.large_file = SimpleUploadedFile("large_image.jpg", b"0" * (3 * 1024 * 1024), content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(document=self.document, file=self.large_file, owner=self.user)

    @patch("documents.services.DocumentHeavyProcessingService.optimize_image")
    def test_optimize_image_success(self, mock_optimize_image):
        """Тест, подтверждающий, что метод оптимизации ВЫЗЫВАЕТСЯ когда нужно"""

        DocumentHeavyProcessingService.optimize_image(self.document_file.file)

        mock_optimize_image.assert_called_once_with(self.document_file.file)

    def test_optimize_image_actually_reduces_size(self):
        """Интеграционный тест реального уменьшения размера файла"""

        small_file = SimpleUploadedFile(
            "small_test.jpg", b"x" * 500, content_type="image/jpeg"  # 500 байт - точно меньше 10MB
        )

        result = DocumentHeavyProcessingService.optimize_image(small_file)

        self.assertIsNone(result)


class ArchiveOldDocumentTaskTest(APITestCase):
    """Тест кейс для проверки работы сервиса и задачи по переносу документов в архив"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.large_file = SimpleUploadedFile("large_image.jpg", b"0" * (5 * 1024 * 1024), content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.large_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )

        Folder.ensure_system_folders()

        self.client.force_authenticate(user=self.user)

    @patch("documents.tasks.archive_old_documents.delay")
    @patch("documents.tasks.timezone")
    def test_approve_document_triggers_archive_task(self, mock_timezone, mock_archive_task):
        """Тест, что одобрение документа запускает задачу архивации"""
        self.client.force_authenticate(user=self.admin)

        # Настраиваем мок времени
        mock_now = datetime(2025, 9, 12, 12, 0, 0)
        mock_timezone.localtime.return_value = mock_now

        url = reverse("documents:queueitem-approve", kwargs={"pk": self.queue_item.pk})
        data = {"status": "approved"}

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_archive_task_returns_correct_count(self):
        """Тест проверка, что задача возвращает правильное количество архивированных документов"""

        for i in range(3):
            Document.objects.create(
                title=f"Old Doc {i}",
                owner=self.user,
                status="approved",
                reviewed_at=timezone.now() - timedelta(hours=2),
            )

        result = archive_old_documents()
        self.assertEqual(result, 3)

    @patch("documents.tasks.timezone")
    def test_task_archive_old_documents_delay_called(self, mock_timezone):
        """Тест успешного вызова задачи по переносу файлов в архив"""

        self.client.force_authenticate(user=self.admin)

        old_document = Document.objects.create(
            title="Test Document for Archive",
            status="approved",
            owner=self.user,
            assigned_admin=self.admin,
            reviewed_at=timezone.localtime() - timedelta(hours=2),
            uploaded_at=timezone.localtime() - timedelta(hours=3),
            reviewed_by=self.admin,
        )

        archive_documents = Document.objects.filter(status="archived").count()
        self.assertEqual(archive_documents, 0)

        mock_now = timezone.localtime()
        mock_timezone.localtime.return_value = mock_now

        from documents.tasks import archive_old_documents

        archive_old_documents()  # Без .delay()!

        archive_documents_now = Document.objects.filter(status="archived").count()

        print(f"Найдено архивных документов: {archive_documents_now}")
        print(f"Статус тестового документа: {old_document.status}")

        self.assertEqual(archive_documents_now, 1)

        old_document.refresh_from_db()

        self.assertEqual(old_document.status, "archived")


class DocumentServiceTest(APITestCase):
    """ "Тест кейс для проверки работы сервиса документов"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.admin_2 = User.objects.create(
            email="test2adminuser@example.com",
            password="testpass123",
            first_name="Admin2",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_2 = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin_2,
            title="Test document_2",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.approvalqueue_2 = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin_2)
        self.approvalqueue_3 = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin_2)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )
        self.queue_item_2 = QueueItem.objects.create(
            queue=self.approvalqueue_2,
            document=self.document_2,
            position=1,
        )

        Folder.ensure_system_folders()

        # self.client.force_authenticate(user=self.user)

    def test_create_document_service_invalid(self):
        """
        Тест сервиса создания документа, срабатывание исключения
        при попытке загрузки документа без файла
        """

        self.client.force_authenticate(user=self.user)

        document_data = {
            "title": "Test document service invalid",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
        }

        with self.assertRaises(DjangoValidationError) as context:
            DocumentService.create_document(document_data, self.user, None)

        self.assertIn("Загрузите хотя бы один файл!", str(context.exception))

    def test_create_document_service(self):
        """Тест работы сервиса создания документа"""

        document_data = {
            "title": "Test document service invalid",
            "assigned_admin": self.admin,
        }
        mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")

        document = DocumentService.create_document(document_data, self.user, [mock_file])

        self.assertEqual(document.title, "Test document service invalid")
        self.assertEqual(document.owner, self.user)
        self.assertEqual(document.assigned_admin, self.admin)
        self.assertEqual(document.status, "pending")

    def test_get_next_available_admin(self):
        """
        Тест проверка, что документу назначается администратор,
        путем определения следующего доступного администратора
        """

        from .services import get_next_available_admin

        self.client.force_authenticate(user=self.admin)
        self.client.force_authenticate(user=self.admin_2)
        self.client.force_authenticate(user=self.superuser)

        available_admin = get_next_available_admin(exclude_admin=self.document.assigned_admin)
        print(f"available_admin: {available_admin}")

        active_admins = User.objects.filter(
            is_staff=True, is_superuser=False, approval_queue__is_stop=False
        ).distinct()
        print(f"active_admins333: {[active_admin for active_admin in active_admins]}")

        all_queues = ApprovalQueue.objects.all()
        for queue in all_queues:
            print(f"queue.items.count(): {queue.items.count()}")
            if queue.items.count() == 0:
                print(f"selected_queue999: {queue.approver.email}")
                selected_admin = queue.approver.email

                self.assertEqual(available_admin.email, selected_admin)


class DocumentAdminTest(APITestCase):
    """ "Тест кейс для проверки работы 'DocumentAdmin'"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.admin_2 = User.objects.create(
            email="test2adminuser@example.com",
            password="testpass123",
            first_name="Admin2",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_2 = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin_2,
            title="Test document_2",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.approvalqueue_2 = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.approvalqueue_3 = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin_2)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )
        self.queue_item_2 = QueueItem.objects.create(
            queue=self.approvalqueue_2,
            document=self.document_2,
            position=1,
        )

        Folder.ensure_system_folders()

    def test_change_admin_action(self):
        """
        Тест проверяет, что суперпользователь может сменить
        ответственного администратора документов
        """

        from .services import get_next_available_admin

        self.client.force_authenticate(user=self.admin)
        self.client.force_authenticate(user=self.admin_2)
        self.client.force_authenticate(user=self.superuser)

        factory = RequestFactory()
        request = factory.get("/admin/")
        request.user = self.superuser

        document_admin = DocumentAdmin(model=Document, admin_site=admin.site)

        documents = Document.objects.filter(assigned_admin=self.admin)
        original_admin = self.document.assigned_admin

        with patch("documents.admin.DocumentAdmin.message_user"):
            with patch("documents.admin.send_single_document_email.delay"):
                document_admin.change_admin_action(request=request, queryset=documents)

                self.document.refresh_from_db()

                self.assertNotEqual(self.document.assigned_admin, original_admin)


class ApprovalQueueAdminTest(APITestCase):
    """Тест кейс для проверки работы 'ApprovalQueueAdmin"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )

        Folder.ensure_system_folders()

    def test_approve_document(self):
        """Тест одобрения документа из админки"""

        approval_admin = ApprovalQueueAdmin(model=ApprovalQueue, admin_site=admin.site)
        factory = RequestFactory()
        request = factory.get("/admin/")
        request.user = self.admin
        request.META = {"HTTP_REFERER": "/admin/"}

        with patch("documents.admin.DocumentService.handle_queue_action") as mock_handle:
            with patch("documents.admin.Document.objects.get") as mock_get:
                with patch("documents.admin.ApprovalQueueAdmin._handle_queueitem_action") as mock_handle_action:
                    real_time = timezone.localtime()

                    mock_handle.return_value = {
                        "success": True,
                        "document_id": self.document.pk,
                        "message": "Документ одобрен",
                    }
                    mock_get.return_value = self.document

                    with patch("documents.admin.timezone.localtime", return_value=real_time):
                        result = approval_admin.approve_document(
                            request=request, object_id=self.approvalqueue.pk, item_id=self.queue_item.pk
                        )

                        self.assertIsInstance(result, HttpResponseRedirect)
                        self.assertEqual(result.url, "/admin/")

                        mock_handle.assert_called_with(self.queue_item.pk, self.admin, "approve")
                        mock_get.assert_called_with(id=self.document.pk)
                        mock_handle_action.assert_called_with(request, mock_handle.return_value)

    def test_reject_document(self):
        """Тест отклонения документа из админки"""

        approval_admin = ApprovalQueueAdmin(model=ApprovalQueue, admin_site=admin.site)
        factory = RequestFactory()
        request = factory.get("/admin/")
        request.user = self.admin
        request.META = {"HTTP_REFERER": "/admin/"}

        with patch("documents.admin.DocumentService.handle_queue_action") as mock_handle:
            with patch("documents.admin.Document.objects.get") as mock_get:
                with patch("documents.admin.ApprovalQueueAdmin._handle_queueitem_action") as mock_handle_action:
                    real_time = timezone.localtime()

                    mock_handle.return_value = {
                        "success": True,
                        "document_id": self.document.pk,
                        "message": "Документ отклонен!",
                    }
                    mock_get.return_value = self.document

                    with patch("documents.admin.timezone.localtime", return_value=real_time):
                        result = approval_admin.reject_document(
                            request=request, object_id=self.approvalqueue.pk, item_id=self.queue_item.pk
                        )

                        self.assertIsInstance(result, HttpResponseRedirect)
                        self.assertEqual(result.url, "/admin/")

                        mock_handle.assert_called_with(self.queue_item.pk, self.admin, "reject")
                        mock_get.assert_called_with(id=self.document.pk)
                        mock_handle_action.assert_called_with(request, mock_handle.return_value)


class ServicesSetupTaskTest(APITestCase):
    """Тест кейс для проверки создания задачи по архивации документов"""

    def setUp(self):
        """Инициализация тестовых данных"""

        PeriodicTask.objects.all().delete()

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )

        Folder.ensure_system_folders()

    def tearDown(self):
        """Удаление всех связанных задач (на случай, если тест упал на середине)"""
        PeriodicTask.objects.filter(name__contains=f"Document-{self.document.pk}").delete()

    def test_setup_task_archive_old_documents(self):
        """Тест создания расписания для переноса документа в архив"""

        setup_task_archive_old_documents(self.document.pk)

        task = PeriodicTask.objects.filter(name="Archive old documents daily").first()

        self.assertTrue(task, "Периодическая задача не была создана")
        self.assertEqual(task.task, "documents.tasks.archive_old_documents")
        self.assertEqual(task.name, "Archive old documents daily")


class OptimizeTaskTest(APITestCase):
    """Тест кейс для проверки работы задачи по оптимизации файлов"""

    def setUp(self):
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User", is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document", content_type=content_type, defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document", content_type=content_type, defaults={"name": "Can reject document"}
        )

        self.admin.user_permissions.add(approve_perm, reject_perm)
        self.admin.save()

        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        self.large_file = SimpleUploadedFile("large_image.jpg", b"0" * (4 * 1024 * 1024), content_type="image/jpeg")
        self.large_file = SimpleUploadedFile(
            "test_large.jpg",
            DocumentHeavyProcessingService.generate_test_image_content(width=2000, height=2000),  # Большое изображение
            content_type="image/jpeg",
        )
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
            # files=self.large_file,
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document, file=self.large_file, owner=self.user, original_name="test_large_image.jpg"
        )
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )

        Folder.ensure_system_folders()

    @patch("documents.tasks.optimize_image_task.delay")
    def test_optimize_image_task(self, mock_delay):
        """Тест что задача оптимизации ставится в очередь"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {
            "title": "Test Document for optimize",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "files": self.large_file,
        }

        response = self.client.post(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertTrue(Document.objects.filter(title="Test Document for optimize").exists())
        data = response.json()
        document_id = response.data["data"]["id"]
        document = Document.objects.get(id=document_id)
        document_files = DocumentFile.objects.filter(document=document)
        document_file_id = [doc.id for doc in document_files]

        from documents.tasks import optimize_image_task

        mock_delay.assert_called_once_with(document_file_id[0])

    def test_optimize_image_task_success(self):
        """Тест УСПЕШНОЙ оптимизации (возвращает 'success')"""

        document_file = DocumentFile.objects.create(
            document=self.document, file=self.large_file, owner=self.user, original_name="test_image.jpg"
        )

        with patch("documents.services.DocumentHeavyProcessingService.optimize_image") as mock_optimize:
            # with patch("documents.tasks.os.path.basename") as mock_basename:
            mock_output = io.BytesIO(b"fake_optimized_image_data")
            mock_optimize.return_value = mock_output
            result = optimize_image_task(document_file.id)

            self.assertEqual(result, "success")
            mock_optimize.assert_called_once()

    def test_optimize_image_task_error(self):
        """Тест ПРОПУСКА оптимизации (возвращает 'skipped')"""

        document_file = DocumentFile.objects.create(
            document=self.document, file=self.mock_file, owner=self.user, original_name="test_image.jpg"
        )

        with patch("documents.services.DocumentHeavyProcessingService.optimize_image") as mock_optimize:
            mock_optimize.return_value = None

            result = optimize_image_task(document_file.id)

            self.assertEqual(result, "skipped")
            mock_optimize.assert_called_once()


def test_optimize_image_task_file_not_found(self):
    """Тест когда файл не найден в базе"""

    # Создаем и сразу удаляем файл
    document_file = DocumentFile.objects.create(
        document=self.document, file=self.mock_file, owner=self.user, original_name="test_image.jpg"
    )
    file_id = document_file.id
    document_file.delete()  # Удаляем файл

    result = optimize_image_task(file_id)

    self.assertEqual(result, None)


def test_optimize_image_task_no_file(self):
    """Тест когда у файла нет содержимого"""

    document_file = DocumentFile.objects.create(
        document=self.document, file=None, owner=self.user, original_name="test_image.jpg"
    )

    result = optimize_image_task(document_file.id)

    self.assertEqual(result, None)
