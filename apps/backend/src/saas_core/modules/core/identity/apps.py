from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_out


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.core.identity"
    label = "identity"
    verbose_name = "Identity"

    def ready(self) -> None:
        # Every logout, the admin's included, ends its tracked session row
        # (platform settings plan 0c).
        from .sessions import revoke_logged_out_session  # noqa: PLC0415

        user_logged_out.connect(
            revoke_logged_out_session, dispatch_uid="identity.revoke_logged_out_session"
        )
