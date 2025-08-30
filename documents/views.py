from typing import Any, Sequence, Union

from django.db.models import QuerySet

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.serializers import BaseSerializer
from rest_framework import permissions
from rest_framework.permissions import BasePermission, IsAuthenticated, OperandHolder, SingleOperandHolder


from .models import Document
from .permissions import IsOwnerOrAdmin, CanApproveDocument, CanRejectDocument
from .serializers import DocumentSerializer
from .paginators import DocumentPaginator
from .tasks import send_document_status_email


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

        if user.has_perm("documents.view_all_documents"):
            return Document.objects.all()
        return Document.objects.filter(owner=user)

    @action(detail=True, methods=["post"], permission_classes=[CanApproveDocument])
    def approve(self, request: Request, pk=None) -> Response:
        """Действие подтверждения документа и добавления задачи в очередь Celery"""

        document = self.get_object()
        document.status = "approved"
        document.reviewed_by = request.user
        document.save()

        send_document_status_email.delay(
            document_id=document.pk,
            status="approved",
            comment=document.review_comment
        )

        return Response({"status": "approved"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[CanRejectDocument])
    def reject(self, request, pk=None):
        """Действие отклонения документа"""

        document = self.get_object()
        document.status = "rejected"
        document.reviewed_by = request.user
        document.save()

        send_document_status_email.delay(
            document_id=document.pk,
            status="rejected",
            comment=document.review_comment
        )

        return Response({"status": "rejected"}, status=status.HTTP_200_OK)

    def get_permissions(self) -> Sequence[Any]:
        """
        Управление разрешениями:
        (POST /documents/       # Создание: любой аутентифицированный пользователь
        GET /documents/         # Список: владелец или админ (видят разные наборы)
        GET /documents/{id}/    # Просмотр: только владелец документа
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
            return [permissions.IsAuthenticated(), IsOwnerOnly()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        """Выбираем сериализатор в зависимости от прав пользователя"""

        if self.request.user.has_perm("documents.view_all_documents"):
            return DocumentAdminSerializer
        return DocumentSerializer

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Создает объект 'Document' и автоматически назначает пользователя"""

        document = serializer.save(owner=self.request.user)
        print(f"Создан документ: {document}")

        if self.request.user.email:
            send_document_status_email.delay(
                document_id=document.pk,
                status="pending",
        )
        else:
            print("У пользователя нет email, уведомление не отправлено")

    # def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
    #     """Обновление привычки"""
    #
    #     instance = self.get_object()
    #
    #     partial = kwargs.pop("partial", False)
    #     serializer = self.get_serializer(
    #         instance,
    #         data=request.data,
    #         partial=partial,
    #     )
    #     serializer.is_valid(raise_exception=True)
    #     self.perform_update(serializer)
    #
    #     return Response(serializer.data)

