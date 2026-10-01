"""Installs `MfaAdminSite` as Django's default admin site.

Outside `saas_core.modules` on purpose: the composition tests read module apps
from `INSTALLED_APPS` by that prefix, and the site itself lives in identity.
"""

from django.contrib.admin.apps import AdminConfig


class MfaAdminConfig(AdminConfig):
    default_site = "saas_core.modules.core.identity.admin_site.MfaAdminSite"
