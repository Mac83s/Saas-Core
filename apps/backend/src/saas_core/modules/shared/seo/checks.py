from typing import Any

from django.conf import settings
from django.core.checks import Error, register

from .source import SeoUnavailable, SourceConfig


@register()
def check_source_configuration(app_configs: Any, **kwargs: Any) -> list[Error]:
    names = (
        "SEO_SSA_BASE_URL",
        "SEO_SSA_SOURCE_ID",
        "SEO_SSA_SERVICE_KEY",
        "SEO_SSA_CALLBACK_SECRET",
        "SEO_SSA_PRODUCT_ID",
        "SEO_SSA_DEPLOYMENT_ID",
        "SEO_AUDIT_CREDIT_OPERATION",
    )
    if not any(getattr(settings, name, "") for name in names):
        return []
    try:
        SourceConfig.configured()
    except SeoUnavailable:
        return [Error("SSA audit source configuration is incomplete or invalid.", id="seo.E001")]
    return []
