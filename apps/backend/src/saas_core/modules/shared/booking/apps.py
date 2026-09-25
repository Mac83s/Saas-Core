from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.booking"
    label = "booking"
    verbose_name = "Booking"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from .models import PublicBookingRoute, ReminderRoute, SelfServiceRoute

        # Pre-tenant routing indexes: erasing the organization takes them too,
        # or its public slug would route a new organization to the old tenant.
        for name, model in (
            ("public_route", PublicBookingRoute),
            ("self_service_route", SelfServiceRoute),
            ("reminder_route", ReminderRoute),
        ):
            register_erasure_rows(f"shared.booking.{name}", model, "organization_id")
