"""ASGI config for hep_data_azure."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hep_data_azure.settings.dev")

application = get_asgi_application()

