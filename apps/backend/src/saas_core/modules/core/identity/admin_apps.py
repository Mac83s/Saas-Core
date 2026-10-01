"""Installs `MfaAdminSite` as Django's default admin site.

Kept apart from `apps.py`: a second AppConfig subclass there would make Django
ask which of the two is the identity app's default.
"""

from django.contrib.admin.apps import AdminConfig


class MfaAdminConfig(AdminConfig):
    default_site = "saas_core.modules.core.identity.admin_site.MfaAdminSite"
