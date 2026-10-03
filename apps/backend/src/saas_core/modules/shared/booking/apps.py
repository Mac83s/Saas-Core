from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.booking"
    label = "booking"
    verbose_name = "Booking"

    def ready(self) -> None:
        from django.db.models.signals import post_delete, post_save

        from saas_core.modules.core.organizations.api import register_invitation_accepted
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows
        from saas_core.modules.shared.profiles.api import register_catalog_terms

        from .catalog_terms import service_changed, service_names
        from .facts import register_core_facts
        from .models import PublicBookingRoute, ReminderRoute, SelfServiceRoute, Service
        from .notify import register_templates
        from .staff import link_on_join

        # The person the office added is the one who accepts the invitation.
        register_invitation_accepted(link_on_join)
        # A demo day board on a staging stack (seed_demo).
        from saas_core.modules.core.organizations.demo import register_demo_part

        from .demo import seed_calendar

        register_demo_part("booking.calendar", seed_calendar, order=30)
        # What the people on a visit hear about it (ADR-058 §9).
        register_templates()
        # A person's results and history: the calendar's and the account's (phase 5).
        register_core_facts()
        # Services and working hours for the assistant (ADR-076, A1b-12).
        from .command_declarations import register_booking_commands

        register_booking_commands()
        # Reminders and the online-booking pause, on core's settings registry (ADR-078).
        from .company_settings import register_company_settings

        register_company_settings()
        # The booking catalogue as a translation source (ADR-069, TL12c).
        from .translation_source import register_catalog_source

        register_catalog_source()
        # Service names make a company findable in the catalogue (ADR-064).
        register_catalog_terms("shared.booking.services", service_names)
        post_save.connect(service_changed, sender=Service, dispatch_uid="booking.catalog.save")
        post_delete.connect(service_changed, sender=Service, dispatch_uid="booking.catalog.delete")

        # Pre-tenant routing indexes: erasing the organization takes them too,
        # or its public slug would route a new organization to the old tenant.
        for name, model in (
            ("public_route", PublicBookingRoute),
            ("self_service_route", SelfServiceRoute),
            ("reminder_route", ReminderRoute),
        ):
            register_erasure_rows(f"shared.booking.{name}", model, "organization_id")
