from django.urls import path
from rest_framework.routers import DefaultRouter

from documents.apps import DocumentsConfig
from documents.views import (
    DocumentViewSet,
)

app_name = DocumentsConfig.name


router = DefaultRouter()
router.register(r"", DocumentViewSet, basename="documents")

urlpatterns = [

] + router.urls
