from typing import Any, Protocol

from rest_framework import permissions
from rest_framework.request import Request

from django.core.exceptions import PermissionDenied
from django.views import View

from users.models import User


class HasOwner(Protocol):
    user: User


class IsOwnerOrAdmin(permissions.BasePermission):
    """Разрешение только для владельца документа"""

    def has_object_permission(self, request: Request, view: View, obj: HasOwner) -> bool:
        """
        Все права по работе с документами у владельца.
        Админ может просматривать все документы.
        """

        if obj and obj.owner == request.user:
            return True
        return request.user.has_perm("documents.view_all_documents")


class CanApproveDocument(permissions.BasePermission):
    """Разрешение на подтверждение документов"""

    def has_permission(self, request: Request, view: View) -> bool:
        """Проверка права на уровне запроса"""
        return request.user.has_perm("documents.can_approve_document")

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Проверка права на уровне объекта"""
        return request.user.has_perm("documents.can_approve_document")


class CanRejectDocument(permissions.BasePermission):
    """Разрешение на отклонение документов"""

    def has_permission(self, request: Request, view: View) -> bool:
        """Проверка права на уровне запроса"""
        return request.user.has_perm("documents.can_reject_document")

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        """Проверка права на уровне объекта"""
        return request.user.has_perm("documents.can_reject_document")



