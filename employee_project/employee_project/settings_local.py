# Local development overrides
from .settings import *
import os

# Force development mode
DEBUG = True
ALLOWED_HOSTS = ['*']

# Simple database for development (optional - keeps your PostgreSQL)
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db_local.sqlite3',
#     }
# }

# Disable Celery for development (tasks run synchronously)
# Enable Celery for development to test concurrency
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False

# Development-specific Celery settings
CELERY_WORKER_CONCURRENCY = 4  # Adjust based on your machine
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50  # Restart worker after 50 tasks to prevent memory leaks

# Simple CORS for development
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Disable authentication for development
REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'] = [
    'rest_framework.permissions.AllowAny',
]

# Disable throttling
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '10000/hour',
    'user': '10000/hour',
}

print("🔧 Development settings loaded - Celery disabled, simple caching enabled")