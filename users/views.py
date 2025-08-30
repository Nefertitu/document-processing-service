from typing import Any, List

from rest_framework import permissions, serializers, viewsets
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.serializers import BaseSerializer

from django.db.models import QuerySet

from .models import User
from .permissions import IsSelfOnly, CanViewAllUsers, CanDeleteUsers
from .serializers import UserProfileSerializer


class UserCreateApiView(CreateAPIView):
    """Класс для создания профиля пользователя"""

    serializer_class = UserProfileSerializer
    queryset = User.objects.all()
    permission_classes = (AllowAny,)

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Метод для создания профиля пользователя (POST /register/)"""

        user = serializer.save(is_active=True)
        user.set_password(user.password)
        user.save()


class UserProfileViewSet(viewsets.ModelViewSet):
    """Управление пользователями (требуется аутентификация)"""

    serializer_class = UserProfileSerializer
    queryset = User.objects.all()

    def get_permissions(self) -> List[permissions.BasePermission]:
        """
        Управление разрешениями:
        (GET /users/        # Список (общий только админы, аутентифицированные пользователи свой)
        GET /users/{id}/    # Просмотр (только владелец)
        PUT /users/{id}/    # Полное обновление (только владелец)
        PATCH /users/{id}/  # Частичное обновление (только владелец)
        DELETE /users/{id}/ # Удаление (только админы)
        )
        """

        if self.action == "create":
            return [permissions.AllowAny()]
        elif self.action in ["retrieve", "update", "partial_update"]:
            return [permissions.IsAuthenticated(), IsSelfOnly()]

        elif self.action == "list":
            return [permissions.IsAuthenticated(), CanViewAllUsers()]

        elif self.action == "destroy":
            return [permissions.IsAuthenticated(), CanDeleteUsers()]

        else:
            return [permissions.IsAuthenticated()]

    def get_queryset(self) -> QuerySet[User]:
        """Фильтрация - пользователь видит только себя, админ всех"""

        if self.request.user.has_perm("users.view_all_users"):
            return User.objects.all()
        return User.objects.filter(pk=self.request.user.id)



