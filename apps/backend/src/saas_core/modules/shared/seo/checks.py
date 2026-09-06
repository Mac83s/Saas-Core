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
        "SEO_GSC_REDIRECT_URI",
    )
    if not any(getattr(settings, name, "") for name in names):
        return []
    try:
        SourceConfig.configured(
            require_audit=bool(
                settings.SEO_SSA_CALLBACK_SECRET or settings.SEO_AUDIT_CREDIT_OPERATION
            )
        )
        if getattr(settings, "SEO_GSC_REDIRECT_URI", ""):
            from .gsc.settings import redirect_uri

            redirect_uri()
    except SeoUnavailable:
        return [Error("SSA audit source configuration is incomplete or invalid.", id="seo.E001")]
    return []
