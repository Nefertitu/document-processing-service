from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Пользователь"""

    password = serializers.CharField(write_only=True, required=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "full_name",
            "avatar",
        )
        extra_kwargs = {
            "password": {"write_only": True},
        }

    def create(self, validated_data):
        """Хеширование пароля перед сохранением"""

        password = validated_data.pop("password")
        user = User.objects.create(
            email=validated_data["email"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            avatar=validated_data.get("avatar", None),
        )
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        """Если обновляется пароль - хешируем его"""

        password = validated_data.pop("password", None)
        if password:
            instance.set_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return super().update(instance, validated_data)
