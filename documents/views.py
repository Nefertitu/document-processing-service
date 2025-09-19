import os
from typing import Any, Sequence, Union, Type

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, QuerySet
from django.http import FileResponse, HttpResponseForbidden
from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework import permissions, status, viewsets
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated, OperandHolder, SingleOperandHolder
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from .models import ApprovalQueue, Document, DocumentFile, Folder, QueueItem
from .paginators import ApprovalItemPaginator, DocumentPaginator, QueueItemPaginator
from .permissions import CanAccessDocumentFile, CanApproveDocument, CanRejectDocument
from .serializers import (
    ApprovalQueueSerializer,
    DocumentAdminSerializer,
    DocumentFileSerializer,
    DocumentSerializer,
    FolderSerializer,
    QueueItemSerializer,
)
from .services import DocumentHeavyProcessingService, DocumentService, QueueService, setup_task_archive_old_documents
from .tasks import send_single_document_email


class FolderViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с папками"""

    queryset = Folder.objects.all()
    serializer_class = FolderSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    permission_classes = [permissions.IsAdminUser()]

    def get_queryset(self) -> QuerySet[Folder]:
        """Получаем базовый queryset папок"""

        queryset = Folder.objects.all()

        if not self.request.user.is_superuser:
            queryset = queryset.annotate(
                pending_count=Count(
                    "documents", filter=Q(documents__status="pending", documents__assigned_admin=self.request.user)
                ),
                approved_count=Count(
                    "documents", filter=Q(documents__status="approved", documents__assigned_admin=self.request.user)
                ),
                rejected_count=Count(
                    "documents", filter=Q(documents__status="rejected", documents__assigned_admin=self.request.user)
                ),
                archived_count=Count(
                    "documents", filter=Q(documents__status="archived", documents__assigned_admin=self.request.user)
                ),
            )
        else:
            queryset = queryset.annotate(
                pending_count=Count(
                    "documents",
                    filter=Q(
                        documents__status="pending",
                    ),
                ),
                approved_count=Count(
                    "documents",
                    filter=Q(
                        documents__status="approved",
                    ),
                ),
                rejected_count=Count(
                    "documents",
                    filter=Q(
                        documents__status="rejected",
                    ),
                ),
                archived_count=Count(
                    "documents",
                    filter=Q(
                        documents__status="archived",
                    ),
                ),
            )

        return queryset

    def get_serializer_class(self) -> Type[FolderSerializer]:
        """Возвращает класс сериализатора"""
        return FolderSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с документами"""

    serializer_class = DocumentSerializer
    pagination_class = DocumentPaginator
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = [
        "title",
        "owner__full_name",
        "reviewed_by__full_name",
        "uploaded_at",
    ]  # Пример запроса: /api/documents/?search=financial
    ordering_fields = [
        "uploaded_at",
        "title",
        "assigned_admin",
        "reviewed_at",
        "reviewed_by",
    ]  # Пример запроса: /api/documents/?ordering=-created_at,title
    ordering = ["-uploaded_at"]
    filterset_fields = ["status", "owner"]  # Пример запроса: /api/documents/?status=pending&owner=1

    PermissionClass = Union[type[BasePermission], OperandHolder, SingleOperandHolder]

    def get_queryset(self) -> QuerySet[Document] | None:
        """Фильтрация документов по правам пользователя"""

        user = self.request.user

        if user.is_superuser:
            return Document.objects.all()
        elif user.is_staff:
            return Document.objects.filter(assigned_admin=user)
        else:
            return Document.objects.filter(owner=user)

    def get_permissions(self) -> Sequence[Any]:
        """
        Управление разрешениями:
        (POST /documents/       # Создание: любой аутентифицированный пользователь, но не админ
        GET /documents/         # Список: владелец, админ или суперпользователь (видят разные наборы)
        GET /documents/{id}/    # Просмотр: владелец документа и админ, суперпользователь
        PUT /documents/{id}/    # Полное обновление: запрет
        PATCH /documents/{id}/  # Частичное обновление: админ и суперпользователь
        DELETE /documents/{id}/ # Удаление: только суперпользователь
        POST /documents/        # Подтверждение/Отклонение: только админ с special permissions
        )
        """
        if self.action == "create":
            return [permissions.IsAuthenticated()]
        elif self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        elif self.action in ["partial_update"]:
            return [permissions.IsAdminUser()]
        elif self.action == "destroy":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        """Выбираем сериализатор в зависимости от прав пользователя"""

        user = self.request.user
        if self.action == "create":
            return DocumentSerializer
        elif user.is_staff or user.is_superuser:
            return DocumentAdminSerializer
        return DocumentSerializer

    def perform_create(self, serializer):
        """Устанавливаем владельца автоматически"""
        serializer.save(owner=self.request.user)

    def create(self, request, *args: Any, **kwargs: Any):
        """Только обычные пользователи могут создавать документы"""

        document = None

        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            if request.user.is_staff or request.user.is_superuser:
                return Response(
                    {"error": "Администраторы не могут создавать документы"}, status=status.HTTP_403_FORBIDDEN
                )

            files = request.FILES.getlist("files")

            document = DocumentService.create_document(serializer.validated_data, request.user, files)

            setup_task_archive_old_documents(document.pk)

            send_single_document_email.delay(
                document_id=document.pk, status="pending", comment="Получен новый документ на согласование"
            )

            view_serializer = DocumentSerializer(document, context={"request": request})

            return Response(
                {"data": view_serializer.data, "success": f"Документ успешно создан: '{document.title}'"},
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response({"error": f"Не удалось создать документ: {e}"}, status=status.HTTP_400_BAD_REQUEST)

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

    def perform_update(self, serializer):
        """Если есть комментарий или файл ответа, но нет проверяющего администратора"""

        instance = serializer.instance

        if "review_comment" in serializer.validated_data or "file_answer" in serializer.validated_data:
            serializer.validated_data["reviewed_by"] = self.request.user
            instance.save()

        super().perform_update(serializer)


class ApprovalQueueViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с очередью администратора"""

    permission_classes = [IsAdminUser]
    serializer_class = ApprovalQueueSerializer
    paginator_class = ApprovalItemPaginator

    def get_permissions(self) -> Sequence[Any]:
        """Управление разрешениями"""

        if self.action in ["list", "retrieve"]:
            return [permissions.IsAdminUser()]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self) -> QuerySet[ApprovalQueue] | None:
        """
        Фильтрует документы в зависимости от прав пользователя.
        Aдмин видит только свои папки, суперпользователь,- все
        """

        user = self.request.user

        if user.is_superuser:
            queryset = ApprovalQueue.objects.all()
        elif user.is_staff:
            queryset = ApprovalQueue.objects.filter(approver=user)
        else:
            queryset = ApprovalQueue.objects.none()

        return queryset

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:
        """Возвращает класс сериализатора"""
        return ApprovalQueueSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Только суперпользователь и админы могут создавать очереди"""

        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            if not request.user.is_staff or not request.user.is_superuser:
                return Response(
                    {"error": "Создавать очередь могут только суперпользователь или админы"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer.save()
            return Response(
                {"data": serializer.data, "success": "Очередь успешно создана!"},
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response({"error": f"Не удалось создать очередь: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Возвращает список очередей в зависимости от прав"""

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Удаление очереди.
        Суперпользователь и админы могут удалить только пустую очередь.
        """

        instance = self.get_object()
        user = request.user

        documents_count = instance.items.count()

        if user.is_superuser:
            if documents_count > 0:
                return Response(
                    {
                        "error": "Нельзя удалить очередь с документами. "
                        "Сначала нужно обработать (Одобрить/Отклонить) имеющиеся документы. "
                        "Суперпользователь может переназначить ответственного администратора."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            elif documents_count == 0:
                instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        else:
            return Response({"error": "У вас нет прав для удаления очереди."}, status=status.HTTP_403_FORBIDDEN)


class QueueItemViewSet(viewsets.ModelViewSet):
    """ViewSet для работы с документами в очереди"""

    serializer_class = QueueItemSerializer
    pagination_class = QueueItemPaginator
    queryset = QueueItem.objects.all()

    def get_permissions(self) -> Sequence[Any]:
        """Разные права для разных действий:
        - Отклонение/Одобрение: суперпользователь и ответственный администратор
        - Просмотр: доступен всем
        - Остальное: только админ или суперпользователь
        """

        if self.action in ["approve", "reject"]:
            return [CanApproveDocument(), CanRejectDocument()]
        elif self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        else:
            return [permissions.IsAdminUser()]

    def get_queryset(self) -> QuerySet[QueueItem] | None:
        """Фильтрация документов по правам пользователя"""

        user = self.request.user

        if user.is_superuser:
            return QueueItem.objects.filter(document__status="pending")
        if (
            user.is_staff
            and user.has_perm("documents.can_approve_document")
            and user.has_perm("documents.can_reject_document")
        ):
            return QueueItem.objects.filter(document__status="pending", document__assigned_admin=user)
        if user.is_authenticated:
            return QueueItem.objects.filter(document__status="pending", document__owner=user)
        else:
            return QueueItem.objects.none()

    def get_object(self) -> QueueItem:
        """Получает объект QueueItem и проверяет права доступа пользователя"""

        try:
            obj = QueueItem.objects.get(pk=self.kwargs.get("pk"))

            user = self.request.user

            if (
                user.is_superuser
                or (user.is_staff and obj.document.assigned_admin == user)
                or obj.document.owner == user
            ):
                return obj

            raise PermissionDenied("У вас нет прав для доступа к этому элементу очереди")

        except QueueItem.DoesNotExist:
            print("❌ Объект не найден")
            raise Http404("Элемент очереди не существует")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            raise

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Обновление статуса документа, добавление комментария и
        ответного файла доступно только админу
        """

        instance = self.get_object()
        document = instance.document
        print(f"Документ: {document}")

        print(f"🔍 До обновления - temp_review_comment: {getattr(instance, 'temp_review_comment', 'N/A')}")
        print(f"🔍 До обновления - document.review_comment: {document.review_comment}")

        allowed_fields = ["status", "temp_review_comment", "temp_file_answer"]

        filtered_data = {key: value for key, value in request.data.items() if key in allowed_fields}

        serializer = self.get_serializer(
            instance,
            data=filtered_data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        serializer.save()

        print(f"🔍 После сохранения - temp_review_comment: {getattr(instance, 'temp_review_comment', 'N/A')}")
        print(f"🔍 После сохранения - document.review_comment: {document.review_comment}")

        if hasattr(instance, "temp_review_comment") and instance.temp_review_comment:
            document.review_comment = instance.temp_review_comment
            print(f"💬 Установлен комментарий: {instance.temp_review_comment}")

        if hasattr(instance, "temp_file_answer") and instance.temp_file_answer:
            document.file_answer = instance.temp_file_answer
            print(f"📁 Загружен файл: {instance.temp_file_answer.name}")

        instance.save()
        document.save()
        print(f"💾 Документ сохранен с комментарием: {document.review_comment}")

        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: int = None) -> Response:
        """Одобрение документа через сервис с комментарием и/или ответным файлом"""

        review_comment = request.data.get("temp_review_comment", "")
        file_answer = request.data.get("temp_file_answer", None)

        result = DocumentService.handle_queue_action(pk, request.user, "approve", review_comment, file_answer)
        return self._handle_service_response(result)

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: int = None) -> Response:
        """Отклонение документа через сервис с ответным комментарием и/или ответным файлом"""

        review_comment = request.data.get("temp_review_comment", "")
        file_answer = request.data.get("temp_file_answer", "")

        result = DocumentService.handle_queue_action(pk, request.user, "reject", review_comment, file_answer)
        return self._handle_service_response(result)

    def _handle_service_response(self, result: dict) -> Response:
        """Обработка ответа от сервиса"""

        if result["success"]:
            return Response({"message": result["message"]}, status=status.HTTP_200_OK)
        return Response({"error": result["message"]}, status=status.HTTP_400_BAD_REQUEST)


class DocumentFileViewSet(viewsets.ModelViewSet):
    """'ViewSet' для работы с файлами"""

    serializer_class = DocumentFileSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["file", "original_name"]
    ordering_fields = ["uploaded_at", "file__size"]
    ordering = ["-uploaded_at"]

    def get_queryset(self) -> QuerySet[DocumentFile]:
        """Возвращает 'queryset' в зависимости от прав"""

        user = self.request.user

        if user.is_superuser:
            return DocumentFile.objects.all()
        elif user.is_staff:
            return DocumentFile.objects.filter(document__assigned_admin=user)
        else:
            return DocumentFile.objects.filter(owner=user)

    def perform_create(self, serializer) -> None:
        """Автоматическая привязка к пользователю"""
        serializer.save(owner=self.request.user)
