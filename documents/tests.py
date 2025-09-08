from datetime import datetime, time, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APITestCase

from config import settings
from .models import Document, Folder, ApprovalQueue, QueueItem
# from .services import send_telegram_message, setup_habit_reminder
# from .tasks import send_information, send_reminder
from users.models import User


class DocumentTestCase(APITestCase):
    """Тест кейс для проверки CRUD представлений модели 'Document'"""

    def setUp(self) -> None:
        """Инициализация тестовых данных"""

        self.user = User.objects.create(email="testuser@example.com", password="testpass123", is_staff=False)
        self.admin = User.objects.create(email="testadminuser@example.com", password="testpass123", is_staff=True)
        self.approvalqueue = ApprovalQueue.objects.create(title="Test Approval", approver=self.admin)

        Folder.ensure_system_folders()

        self.mock_file = SimpleUploadedFile(
            "test_image.jpg",
            b"file_content",  # Бинарное содержимое файла
            content_type="image/jpeg"
        )

        self.document = Document.objects.create(
            owner=self.user,
            assigned_admin=self.admin,
            title="Test document",
            file=self.mock_file
        )

        self.client.force_authenticate(user=self.user)

    def test_document_retrieve(self) -> None:
        """Тест получения деталей документа"""

        url = reverse("documents:document-detail", kwargs={"pk": self.document.pk})
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data

        self.assertEqual(data.get("title"), self.document.title)
        self.assertEqual(data.get("owner"), self.document.owner.email)
        self.assertEqual(data.get("assigned_admin")["email"], self.admin.email)
        self.assertEqual(data.get("title"), self.document.title)
        self.assertEqual(data.get("status"), "pending")
        self.assertIsNotNone(data.get("file"))
        self.assertEqual(data.get("folder"), "pending")

    def test_document_create(self):
        """Тест создания документа с файлом"""

        url = reverse("documents:document-list")

        mock_file = SimpleUploadedFile(
            "test_document.jpg",
            b"test file content",
            content_type="image/jpeg"
        )

        data = {
            "owner": self.user,
            "title": "Test Document with File",
            "file": mock_file,
            "assigned_admin": self.admin,
        }

        response = self.client.post(url, data, format="multipart")
        print(response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Document.objects.filter(title="Test Document with File").exists())


