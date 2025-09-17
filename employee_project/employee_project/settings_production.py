from .settings import *

# Production security
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com', 'www.your-domain.com', 'api.yourdomain.com']

# Security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Production database with connection pooling
DATABASES['default'].update({
    'CONN_MAX_AGE': 60,  # Shorter connection age
    'OPTIONS': {
        'MAX_CONNS': 20,   # Reduced from 50
        'MIN_CONNS': 5,    # Reduced from 10
        'connect_timeout': 5,
        'sslmode': 'prefer',
    }
})

# Redis cache for production
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 20,
            }
        },
        'TIMEOUT': 300,
    }
}

# Enable Celery for production (async processing)
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False

# Production throttling
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '100/hour',
    'user': '1000/hour', 
    'burst': '60/min',
    'sustained': '1000/day',
    'media_generation': '10/hour'
}

# Require authentication in production
REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'] = [
    'rest_framework.permissions.IsAuthenticated',
]

# CORS for production (restrict to your domains)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    "https://your-domain.com",
    "https://www.your-domain.com",
]

# Production logging
LOGGING['handlers']['file']['filename'] = '/var/log/django/app.log'
LOGGING['handlers']['error_file']['filename'] = '/var/log/django/errors.log'

print("🚀 Production settings loaded - Security enabled, async processing active")