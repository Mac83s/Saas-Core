from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured


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
        from .models import (
            PublicBookingRoute,
            ReminderRoute,
            RequestRoute,
            SelfServiceRoute,
            Service,
        )
        from .notify import register_templates
        from .staff import link_on_join

        register(check_preset_contracts, "booking")
        # The customer's public link, the reminders and the mails to the people
        # on a visit run as the organization's own work (ADR-073 §5).
        from .security import register_service_scopes

        register_service_scopes()
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
        # What the warehouse's usage reports learn about visits (phase 10b).
        from .materials import register_usage

        register_usage()
        # The company's history names a visit, a person and a service (UX-055).
        from .history_targets import register_history_targets

        register_history_targets()
        # Services and working hours for the assistant (ADR-076, A1b-12).
        from .command_declarations import register_booking_commands

        register_booking_commands()
        # Reminders and the online-booking pause, on core's settings registry (ADR-078).
        from .company_settings import register_company_settings

        register_company_settings()
        # What a visit keeps of a customer goes when the customer is stripped
        # (ADR-073 §2).
        from saas_core.modules.shared.customers.api import register_customer_anonymizer

        from .services import strip_customer_visits

        register_customer_anonymizer("shared.booking.visits", strip_customer_visits)
        # Whose card the assistant's conversation may show: the calendar's rule.
        from saas_core.modules.shared.customers.api import register_customer_viewer

        from .people import customers_in_calendar

        register_customer_viewer("bookings", customers_in_calendar)
        # How long customers' personal data is kept (D1, answer 37a).
        from .retention import register_retention

        register_retention()
        # A company with a price list keeps its currency (ADR-073 §8).
        from saas_core.modules.core.organizations.api import register_currency_use

        from .prices import has_prices

        register_currency_use(has_prices)
        # A priced booking is an order `R/…` where the product has commerce
        # (ADR-073 §1).
        from .orders import register as register_order_source

        register_order_source()
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
            ("request_route", RequestRoute),
        ):
            register_erasure_rows(f"shared.booking.{name}", model, "organization_id")


def check_preset_contracts(**_kwargs: object) -> list[Error]:
    """Fails the deploy when the booking presets did not reach the image.

    They are read from disk on first use, so a missing directory or a version
    the manifest names without its file would surface as a 500 the first time
    somebody starts an offer — long after the deploy reported success.
    """
    from .presets import latest_presets

    try:
        latest_presets()
    except ImproperlyConfigured as error:
        return [
            Error(
                str(error),
                hint=(
                    "Skopiuj packages/contracts/booking-presets do obrazu i ustaw zmienną "
                    "środowiskową BOOKING_PRESET_CONTRACTS_PATH."
                ),
                obj=str(settings.BOOKING_PRESET_CONTRACTS_PATH),
                id="booking.E010",
            )
        ]
    return []
