from typing import Any, List

from rest_framework import permissions, serializers, viewsets
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.serializers import BaseSerializer

from users.models import User
from users.permissions import IsOwnerOnly
from users.serializers import UserProfileSerializer


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
        (GET /users/        # Список (только админы)
        GET /users/{id}/    # Просмотр (только владелец)
        PUT /users/{id}/    # Полное обновление (только владелец)
        PATCH /users/{id}/  # Частичное обновление (только владелец)
        DELETE /users/{id}/ # Удаление (только админы)
        )
        """

        if self.action in ["update", "partial_update", "retrieve"]:
            return [IsOwnerOnly()]
        elif self.action in ["list", "destroy"]:
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

