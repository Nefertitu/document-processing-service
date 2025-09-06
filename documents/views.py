import os
from typing import Any, Sequence, Union

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import FileResponse
from django.http import HttpResponseForbidden
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated, OperandHolder, SingleOperandHolder
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from .models import ApprovalQueue, Document, Folder, QueueItem
from .paginators import DocumentPaginator, QueueItemPaginator
from .permissions import IsOwnerOnly, IsOwnerOrAdmin, CanApproveDocument, CanRejectDocument
from .serializers import ApprovalQueueSerializer, DocumentSerializer, DocumentAdminSerializer, FolderSerializer, QueueItemSerializer
from .services import DocumentHeavyProcessingService, DocumentService, QueueService
from .tasks import send_bulk_documents_email, send_single_document_email


class FolderViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с папками"""

    queryset = Folder.objects.all()
    serializer_class = FolderSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    # permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        """Возвращает все папки"""
        return Folder.objects.all()

    def get_serializer_class(self):
        return FolderSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с документами"""

    serializer_class = DocumentSerializer
    permission_classes = [IsOwnerOrAdmin]
    pagination_class = DocumentPaginator

    PermissionClass = Union[type[BasePermission], OperandHolder, SingleOperandHolder]

    def get_queryset(self) -> QuerySet[Document] | None:
        """
        Фильтрует документы в зависимости от прав пользователя.
        Пользователь видит только свои документа, админ - все.
        """
        user = self.request.user

        if user.is_superuser:
            return Document.objects.all()
        return Document.objects.filter(assigned_admin=user)

    def get_permissions(self) -> Sequence[Any]:
        """
        Управление разрешениями:
        (POST /documents/       # Создание: любой аутентифицированный пользователь, но не админ
        GET /documents/         # Список: владелец или админ (видят разные наборы)
        GET /documents/{id}/    # Просмотр: владелец документа и админ
        PUT /documents/{id}/    # Полное обновление: только владелец документа
        PATCH /documents/{id}/  # Частичное обновление: только владелец документа
        DELETE /documents/{id}/ # Удаление: только владелец документа
        POST /documents/        # Подтверждение/Отклонение: только админ с special permissions
        )
        """

        if self.action == "create":
            return [permissions.IsAuthenticated()]
        elif self.action == "list":
            return [permissions.IsAuthenticated()]
        elif self.action in ["retrieve", "update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), IsOwnerOnly(), IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        """Выбираем сериализатор в зависимости от прав пользователя"""

        if self.request.user.has_perm("documents.view_all_documents"):
            return DocumentAdminSerializer
        return DocumentSerializer

    def create(self, request, *args: Any, **kwargs: Any):
        """Только обычные пользователи могут создавать документы"""

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if request.user.is_staff:
            return Response({"error": "Администраторы не могут создавать документы"}, status=status.HTTP_403_FORBIDDEN)

        document = DocumentService.create_document(serializer.validated_data, request.user)

        send_single_document_email.delay(
            document_id=document.pk, status="pending", comment="Получен новый документ на согласование"
        )

        return Response(
            {
                "data": DocumentSerializer(document).data,
                "success": f"Документ успешно создан {document.title}"
            },
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer):
        """Устанавливаем владельца автоматически"""
        serializer.save(owner=self.request.user)

    @login_required
    def protected_media(request, path):
        """View для защиты медиафайлов"""

        file_path = os.path.join(settings.MEDIA_ROOT, path)

        document = Document.objects.get(file__contains=file_path)
        if request.user != document.owner and not request.user.has_perm("view_all_documents"):
            return HttpResponseForbidden("Доступ запрещен")

        if os.path.exists(file_path):
            return FileResponse(open(file_path, "rb"))
        else:
            from django.http import Http404

            raise Http404("Файл не найден")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Обновление документа доступно только его владельцу"""

        instance = self.get_object()

        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)


class ApprovalQueueViewSet(viewsets.ViewSet):
    """ViewSet для работы с очередью администратора"""

    permission_classes = [IsAdminUser(), IsOwnerOnly()]
    serializer_class = ApprovalQueueSerializer

    def get_permissions(self) -> Sequence[Any]:
        """Управление разрешениями"""

        if self.action == "create":
            return [permissions.IsAdminuser()]
        elif self.action == "list":
            return [permissions.IsAdminuser(), IsOwnerOnly()]
        elif self.action in ["retrieve", "update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), IsOwnerOnly()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self) -> QuerySet[ApprovalQueue] | None:
        """
        Фильтрует документы в зависимости от прав пользователя.
        Aдмин видит только свои папки
        """
        user = self.request.user(is_staff=True)

        if user.is_superuser:
            return ApprovalQueue.objects.all()
        return ApprovalQueue.objects.filter(approver=user)


class QueueItemViewSet(viewsets.ViewSet):
    """ViewSet для работы с документами в очереди"""

    permission_classes = [CanApproveDocument, CanRejectDocument, IsAdminUser]
    serializer_class = QueueItemSerializer
    pagination_class = QueueItemPaginator
    queryset = QueueItem.objects.all()

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Обновление статуса документа доступно только админу"""

        instance = self.get_object("status")

        allowed_fields = ["status", "review_comment", "file_answer"]
        data = {key: value for key, value in request.data.items() if key in allowed_fields}

        # partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if "status" in data:
            self._send_status_email(instance.document, data["status"])

        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: int = None) -> Response:
        """Одобрение документа через сервис"""

        result = DocumentService.handle_queue_action(
            pk, request.user, "approve"
        )
        return self._handle_service_response(result)

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: int = None) -> Response:
        """Отклонение документа через сервис"""

        result = DocumentService.handle_queue_action(
            pk,
            request.user,
            "reject",
        )
        return self._handle_service_response(result)

    def _handle_service_response(self, result: dict) -> Response:
        """Обработка ответа от сервиса"""

        if result["success"]:
            return Response({"message": result["message"]}, status=status.HTTP_200_OK)
        return Response({"error": result["message"]}, status=status.HTTP_400_BAD_REQUEST)
