from typing import Any, Protocol

from django.core.exceptions import PermissionDenied
from django.views import View
from rest_framework import permissions
from rest_framework.request import Request

from users.models import User


class HasOwner(Protocol):
    user: User


class IsOwnerOnly(permissions.BasePermission):
    """Разрешение только для владельца объекта"""

    def has_object_permission(self, request: Request, view: Any, obj: HasOwner) -> bool:
        """Проверяет, является ли пользователь владельцем объекта"""

        if request.method in permissions.SAFE_METHODS:
            return True
        return hasattr(obj, "owner") and obj.owner == request.user


class IsOwnerOrAdmin(permissions.BasePermission):
    """Разрешение для владельца документа или админа"""

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


class CanAccessDocumentFile(permissions.BasePermission):
    """Полная проверка прав для 'DocumentFile'"""

    def has_permission(self, request, view):
        """Проверка на уровне запроса"""

        if request.method in permissions.SAFE_METHODS:  # (GET, HEAD, OPTIONS)
            return True
        elif view.action in ["create", "list", "retrieve"]:
            return request.user.is_authenticated
        elif view.action == "destroy":
            return request.user.is_superuser
        else:
            return False

    def has_object_permission(self, request, view, obj):
        """Проверка на уровне конкретного объекта"""

        if request.user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return (
                    obj.owner == request.user or
                    obj.document.assigned_admin == request.user
            )

        return False

