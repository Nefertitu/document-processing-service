import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv(override=True)


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = True if os.getenv("DEBUG") == "True" else False

# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql_psycopg2",
#         "NAME": os.getenv("DATABASE_NAME"),
#         "USER": os.getenv("DATABASE_USER"),
#         "PASSWORD": os.getenv("DATABASE_PASSWORD"),
#         "HOST": os.getenv("DATABASE_HOST"),
#         "PORT": os.getenv("DATABASE_PORT", default="5432"),
#     }
# }


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{os.getenv("POSTGRES_USER")}:{os.getenv("POSTGRES_PASSWORD")}@{os.getenv("POSTGRES_HOST")}:5432/{os.getenv("POSTGRES_DB")}",
)
DATABASES = {"default": dj_database_url.config(default=DATABASE_URL)}


if DEBUG:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [
        "localhost",
        "127.0.0.1",
        os.getenv("SERVER_IP", ""),
    ]

if DEBUG:
    REST_FRAMEWORK = {
        "DEFAULT_FILTER_BACKENDS": [
            "django_filters.rest_framework.DjangoFilterBackend",
            "rest_framework.filters.OrderingFilter",
            "rest_framework.filters.SearchFilter",
        ],
        "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.AllowAny",
        ],
        # "DEFAULT_PERMISSION_CLASSES": [],
        "DATETIME_FORMAT": "%Y-%m-%d %H:%M:%S",
        "USE_TZ": True,
    }


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # other apps
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
    "health_check.contrib.migrations",
    "health_check.contrib.celery",
    "health_check.contrib.redis",
    "rest_framework",
    "django_filters",
    "rest_framework_simplejwt",
    "drf_yasg",
    "django_celery_beat",
    "corsheaders",
    "users",
    "documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"

TIME_ZONE = "Europe/Moscow"

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"

# if DEBUG:
#     STATICFILES_DIRS = [
#         BASE_DIR / "static"
# BASE_DIR / "staticfiles"
#     ]
# else:
#     STATICFILES_DIRS = []

STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHE_ENABLED = True
if CACHE_ENABLED:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.getenv("LOCATION"),
            "TIMEOUT": 300,
            "KEY_PREFIX": "mailing_service",
        }
    }

if "test" in sys.argv:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TASK_SERIALIZER = "json"
else:
    CELERY_BROKER_URL = os.getenv("LOCATION")
    CELERY_RESULT_BACKEND = os.getenv("LOCATION")
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TASK_SERIALIZER = "json"


AUTH_USER_MODEL = "users.User"

LOGIN_REDIRECT_URL = "/admin/"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}


CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_BEAT_SCHEDULE = {
    "archive_old_documents_daily": {
        "task": "documents.tasks.archive_old_documents",
        # "schedule": timedelta(days=1),  # Каждый день
        "schedule": timedelta(minutes=5),  # Для тестирования - каждые 5 минут
    },
}

CELERY_TASK_QUEUES = {
    "celery": {
        "exchange": "celery",
        "routing_key": "celery",
    },
}

CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_CREATE_MISSING_QUEUES = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = os.getenv("EMAIL_PORT")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "False") == "True"  # False
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "True") == "True"  # True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:3000",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:3000",
]

CORS_ALLOW_ALL_ORIGINS = True

HEALTH_CHECK = {
    "DISK_USAGE_MAX": 90,  # Максимальное использование диска в %
    "MEMORY_MIN": 100,  # Минимальная свободная память в MB
}

if not DEBUG:
    # Настройки для Yandex Cloud Object Storage
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    # Yandex Cloud специфичные настройки
    AWS_ACCESS_KEY_ID = os.getenv("YC_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("YC_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("YC_BUCKET_NAME")
    AWS_S3_ENDPOINT_URL = "https://storage.yandexcloud.net"
    AWS_S3_REGION_NAME = "ru-central1"

    # Важные настройки для совместимости с Yandex Cloud
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = "public-read"
    AWS_QUERYSTRING_AUTH = False

    # Дополнительные настройки
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB в байтах
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB в байтах

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "documents": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}
