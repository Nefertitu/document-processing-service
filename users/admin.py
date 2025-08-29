from django.contrib import admin

from users.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Администрирование пользователей. Позволяет управлять
    пользователями, с возможностью фильтрации и поиска."""

    list_display = (
        "id",
        "email",
        "name",
    )
    list_filter = ("email",)
    search_fields = (
        "email",
        "name",
    )
