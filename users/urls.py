from django.contrib.auth.views import LogoutView
from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.apps import UsersConfig
from users.views import (
    UserCreateApiView,
    UserProfileViewSet,
)

app_name = UsersConfig.name


router = DefaultRouter()
router.register(r"", UserProfileViewSet, basename="user")

urlpatterns = [
    path("register/", UserCreateApiView.as_view(), name="register"),
    path("login/", TokenObtainPairView.as_view(permission_classes=(AllowAny,)), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(next_page="users:login"), name="logout"),
] + router.urls
