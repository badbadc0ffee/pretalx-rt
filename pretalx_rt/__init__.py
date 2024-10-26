__version__ = "0.0.2"

from django.conf import settings

settings.EMAIL_BACKEND = "pretalx_rt.mail.RTBackend"
