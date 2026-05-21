"""WSGI config for hep_data_azure."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hep_data_azure.settings.dev")

application = get_wsgi_application()

