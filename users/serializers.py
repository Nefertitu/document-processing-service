from rest_framework import serializers

from users.models import User


class UserProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Пользователь"""

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "avatar",
        )
