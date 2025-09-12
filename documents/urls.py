from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .apps import DocumentsConfig
from .views import ApprovalQueueViewSet, DocumentViewSet, FolderViewSet, QueueItemViewSet, DocumentFileViewSet

app_name = DocumentsConfig.name


router = DefaultRouter()
router.register(r"folders", FolderViewSet, basename="folder")
router.register(r"approval-queue", ApprovalQueueViewSet, basename="approvalqueue")
router.register(r"queue-item", QueueItemViewSet, basename="queueitem")
router.register(r"queueitem-approve", QueueItemViewSet, basename="queueitem-approve")
router.register(r"queueitem-reject", QueueItemViewSet, basename="queueitem-reject")
router.register(r"document-files", DocumentFileViewSet, basename="documentfile")
router.register(r"", DocumentViewSet, basename="document")

urlpatterns = [
    path("", include(router.urls)),
]
