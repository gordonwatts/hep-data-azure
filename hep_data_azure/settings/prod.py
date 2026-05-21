from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
