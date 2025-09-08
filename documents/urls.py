from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .apps import DocumentsConfig
from .views import ApprovalQueueViewSet, DocumentViewSet, FolderViewSet, QueueItemViewSet

app_name = DocumentsConfig.name


router = DefaultRouter()
router.register(r"folders", FolderViewSet, basename="folder")
router.register(r"approval-queue", ApprovalQueueViewSet, basename="approvalqueue")
router.register(r"queue_items", QueueItemViewSet, basename="queueitem")
router.register(r"", DocumentViewSet, basename="document")

urlpatterns = [
    path("", include(router.urls)),
]
