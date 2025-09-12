from datetime import datetime, time, timedelta
from io import StringIO
from unittest.mock import patch
from parameterized import parameterized

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APITestCase

from config import settings
from .models import Document, Folder, ApprovalQueue, QueueItem, DocumentFile
from users.models import User


class DocumentTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'Document'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True
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
            "test_image.jpg",
            b"file_content",  # Бинарное содержимое файла
            content_type="image/jpeg"
        )

        self.client.force_authenticate(user=self.user)
        print(f"📄 Создан документ ID: {self.document.pk}, Title: {self.document.title}, Status: {self.document.status}")

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
            "files": self.mock_file
        }

        response = self.client.post(url, data, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Document.objects.filter(title="Test 2 from 2").exists())

    def test_document_access(self):
        """Тест проверяет доступ к документу разными пользователями"""

        # Проверяем доступ владельца
        self.client.force_authenticate(user=self.user)
        url = reverse("documents:document-detail", kwargs={"pk": self.document.pk})
        response = self.client.get(url)
        print(f"👤 Владелец - Status: {response.status_code}")

        # Проверяем доступ админа
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(url)
        print(f"👨‍💼 Админ - Status: {response.status_code}")

        # Проверяем доступ анонимного пользователя
        self.client.logout()
        response = self.client.get(url)
        print(f"👻 Аноним - Status: {response.status_code}")

    def test_documents_list(self) -> None:
        """Тест списка документов"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")
        response = self.client.get(url)
        data = response.json()
        print(f"Data documents list: {data}")
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
            ("/*/", "Название может состоять из русских и английских букв, цифр, пробелов, дефисов (-) и подчеркиваний (_)!")
        ]
    )
    def test_documents_create_invalid_title(self, invalid_value, expected_error) -> None:
        """Тест создания привычки с невалидным полем 'title'"""

        url = reverse("documents:document-list")
        invalid_data = {
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "title": invalid_value,
        }
        response = self.client.post(url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error, response.data["error"])


class ApprovalQueueTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'ApprovalQueue'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(
            email="testuser@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True
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
            codename="can_approve_document",
            content_type=content_type,
            defaults={"name": "Can approve document"}
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
            "test_image.jpg",
            b"file_content",  # Бинарное содержимое файла
            content_type="image/jpeg"
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
        print(f"Data approval queues1 details: {data}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(data.get("title"), self.approvalqueue.title)
        self.assertEqual(data["approver_info"]["approver_email"], self.admin.email)
        self.assertEqual(data.get("count_documents_in_queue"), 1)
        documents_count = self.approvalqueue.items.all().count()
        print(f"approval_queue.items: {documents_count}")
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
            "files": self.mock_file
        }

        response = self.client.post(url, data, format="multipart")
        print(f"Data currently1 document: {response.data}")

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
        count_approval_queue_items = approval_queue_items.count()
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
        count_approval_queue_items = approval_queue_items.count()
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
            email="testuser@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True
        )

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(QueueItem)

        approve_perm, created = Permission.objects.get_or_create(
            codename="can_approve_document",
            content_type=content_type,
            defaults={"name": "Can approve document"}
        )
        reject_perm, created = Permission.objects.get_or_create(
            codename="can_reject_document",
            content_type=content_type,
            defaults={"name": "Can reject document"}
        )
        view_all_perm, created = Permission.objects.get_or_create(
            codename="view_all_documents",
            content_type=content_type,
            defaults={"name": "Can view all documents"}
        )

        # Назначаем права пользователю
        self.admin.user_permissions.add(approve_perm, reject_perm, view_all_perm)
        self.admin.save()

        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document",
        )
        self.approvalqueue = ApprovalQueue.objects.create(
            title="Test Approval",
            approver=self.admin
        )
        self.queue_item = QueueItem.objects.create(
            queue=self.approvalqueue,
            document=self.document,
            position=1,
        )
        print(f"Создан элемент очереди {self.queue_item}")

        Folder.ensure_system_folders()

        self.mock_file = SimpleUploadedFile(
            "test_image.jpg",
            b"file_content",  # Бинарное содержимое файла
            content_type="image/jpeg"
        )

        self.client.force_authenticate(user=self.user)
        print(f"📄 Создан документ ID: {self.document.pk}, Очередь: {self.approvalqueue.approver}, QueueItem: {self.queue_item.position}")

    def test_queue_item_retrieve(self) -> None:
        """Тест получения деталей элемента очереди"""

        self.client.force_authenticate(user=self.admin)

        url = reverse("documents:queueitem-detail", kwargs={"pk": self.queue_item.pk})

        response = self.client.get(url)
        data = response.data

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data.get("queue"), self.queue_item.queue.pk)
        self.assertEqual(data.get("document"), self.queue_item.document.pk)
        self.assertEqual(data.get("position"), 1)

    def test_document_creation_creates_queue_item(self):
        """Тест, что создание документа автоматически создает элемент очереди"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:document-list")

        data = {
            "title": "Test document for queue_item test",
            "owner": self.user.pk,
            "assigned_admin": self.admin.pk,
            "files": self.mock_file
        }
        print(f"📋 Request data keys: {list(data.keys())}")
        print(f"📋 File type: {type(self.mock_file)}")

        response = self.client.post(url, data, format="multipart")
        print(f"📊 Response status: {response.status_code}")
        print(f"📊 Response data: {response.data}")

        if response.status_code != status.HTTP_201_CREATED:
            self.fail(f"Document creation failed with 400: {response.data}")

        data = response.json()
        print(f"data777: {data}")
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
        self.assertEqual(queue_items_data["queue"], self.approvalqueue.pk)
        self.assertEqual(queue_items_data["document"], self.document.pk)

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

        data = response.json()

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
            email="testuser@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
            is_staff=False
        )
        self.admin = User.objects.create(
            email="testadminuser@example.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True
        )
        self.superuser = User.objects.create(
            email="testsuperuser@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_staff=True,
            is_superuser=True,
        )
        self.mock_file = SimpleUploadedFile(
            "test_image.jpg",
            b"file_content",
            content_type="image/jpeg"
        )
        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document with file",
        )
        self.document_file = DocumentFile.objects.create(
            document=self.document,
            file=self.mock_file,
            owner=self.user,
            original_name="test_image.jpg"
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

        data = {
            "title": "New Document with File",
            "files": self.mock_file,
            "assigned_admin": self.admin.id
        }

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

    def test_document_creation_with_large_file(self) -> None:
        """Тест, подтверждающий, что при создании документа файлы тоже создаются"""

        self.client.force_authenticate(user=self.user)

        url = reverse("documents:documentfile-list")

        large_file = SimpleUploadedFile(
            "large_image.jpg",
            b"0" * (6 * 1024 * 1024),
            content_type="image/jpeg"
        )

        data = {
            "document": self.document,
            "file": large_file,
            "owner": self.user.pk,
        }

        response = self.client.post(url, data, format="multipart")
        print(f"📊 Response status777: {response.status_code}")
        print(f"📊 Response data: {response.data}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        error_message = str(response.data)
        print(f"📋 Error message: {error_message}")

        self.assertIn("Файл слишком большой", error_message)
        self.assertIn("6.0 MB", error_message)









