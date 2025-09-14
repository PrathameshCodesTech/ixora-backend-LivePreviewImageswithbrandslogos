# Local development overrides
from .settings import *

# Override for development
DEBUG = True
ALLOWED_HOSTS = ['*']

# Disable throttling for development
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '1000/hour',
    'user': '10000/hour',
    'burst': '600/min',
    'sustained': '10000/day',
    'media_generation': '100/hour'
}
# Simple CORS fix for development
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ['*']
CORS_ALLOW_METHODS = ['*']
CORS_PREFLIGHT_MAX_AGE = 86400

print("🔧 Development settings loaded with optimizations")
print("📍 Using settings_local.py with custom CORS middleware")