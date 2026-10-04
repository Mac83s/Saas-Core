from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.customers"
    label = "customers"
    verbose_name = "Klienci firm"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import PersonKind, register_person_kind
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from .command_declarations import register_customer_commands
        from .models import DocumentRoute
        from .people import CUSTOMER, PREFIX, customer_cards
        from .translation_source import register_document_source

        # A pre-tenant routing index: erasing the organization takes it too.
        register_erasure_rows("shared.customers.document_route", DocumentRoute, "organization_id")
        # A customer in a command's answer is a handle; the card is made here.
        register_person_kind(PersonKind(kind=CUSTOMER, prefix=PREFIX, cards=customer_cards))
        # What the assistant may read and draft here (ADR-076 §1).
        register_customer_commands()
        # The documents' texts in other languages (ADR-073 §9; needs no engine).
        register_document_source()
        # A demo company's terms and privacy policy, approved before its
        # bookings are made (seed_demo).
        from saas_core.modules.core.organizations.demo import register_demo_part

        from .demo import describe, seed_documents

        register_demo_part("customers.documents", seed_documents, order=25, describe=describe)

        # Each document in force has a page on the company's own site, at
        # `/documents/<its name>/` (ADR-072, slice 5f part 2).
        from saas_core.modules.core.organizations.api import PublicSource, register_public_source

        from .site_pages import PAGE_SEGMENT, no_media, site_page, site_pages

        register_public_source(
            PublicSource(
                "customers.documents",
                no_media,
                page_segment=PAGE_SEGMENT,
                site_page=site_page,
                site_pages=site_pages,
            )
        )
