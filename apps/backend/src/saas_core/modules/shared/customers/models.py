"""The end customer of a company — the one record bookings, orders and the
shop point at (ADR-073 §2) — and the company's documents for its customers
with the journal of who agreed to which (§9)."""

from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class Customer(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    display_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    contact_hash = models.CharField(max_length=64)
    #: A content language from the company's list (ADR-071 pkt 21).
    locale = models.CharField(max_length=10, default="pl")
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        # Only the model's state moved here from booking (ADR-073 §2): the
        # table, its RLS policy and its relation guard are the ones booking's
        # migrations made, under the names they gave them.
        db_table = "booking_customer"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_customer_locale_format_ck",
            ),
        ]
        ordering = ("organization_id", "-created_at", "id")
        indexes = [
            models.Index(
                fields=["organization", "contact_hash"], name="booking_customer_contact_idx"
            )
        ]


class DocumentKind(models.TextChoices):
    BOOKING_TERMS = "booking_terms", "Regulamin rezerwacji"
    SHOP_TERMS = "shop_terms", "Regulamin sklepu"
    PRIVACY_POLICY = "privacy_policy", "Polityka prywatności"
    CANCELLATION_POLICY = "cancellation_policy", "Polityka anulowania"


class CustomerDocument(TenantScopedModel):
    """One of the company's documents for its customers (ADR-073 §9), with the
    draft somebody is still writing. What customers read and agree to is a
    `DocumentVersion`; the draft is nobody's agreement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=32, choices=DocumentKind.choices)
    draft_text = models.TextField(blank=True)
    #: The language the draft is written in; empty while there is no draft.
    draft_locale = models.CharField(max_length=10, blank=True)
    #: Who wrote the draft when it was not a person: the assistant's run.
    draft_origin_ref = models.CharField(max_length=120, blank=True)
    #: Goes up with every change of the draft and every approval; a write
    #: names the one it saw.
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind"], name="customers_document_kind_uq"
            ),
        ]


class DocumentVersion(TenantScopedModel):
    """An approved version, in force from a date. Append-only: the database
    refuses an update and, outside a tenant's erasure, a delete."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    document = models.ForeignKey(
        CustomerDocument, on_delete=models.PROTECT, related_name="versions"
    )
    number = models.PositiveIntegerField()
    #: The language the version was written and approved in.
    source_locale = models.CharField(max_length=10)
    effective_from = models.DateField()
    #: The person who approved it. An id, not a key: the row is never
    #: rewritten, so it cannot follow an account that goes.
    approved_by = models.UUIDField()
    approved_at = models.DateTimeField()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "number"], name="customers_documentversion_number_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(source_locale__regex=r"^[a-z]{2}$"),
                name="customers_documentversion_locale_ck",
            ),
        ]
        ordering = ("document_id", "-number")


class DocumentText(TenantScopedModel):
    """A version's text in one language. Append-only: a correction is the
    next row, so the text a customer agreed to never changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="texts")
    locale = models.CharField(max_length=10)
    text = models.TextField()
    #: sha256 of exactly `text`.
    text_hash = models.CharField(max_length=64)
    #: Empty for the version's own language; for another one, whose text it
    #: translates and who wrote it (`content_protocol.provenance`).
    provenance = models.JSONField(default=dict, blank=True)
    accepted_by = models.UUIDField()
    accepted_at = models.DateTimeField()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="customers_documenttext_locale_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["version", "locale", "-accepted_at"], name="customers_doctext_current_idx"
            ),
        ]
        ordering = ("version_id", "locale", "-accepted_at", "-id")


class ConsentKind(models.TextChoices):
    DOCUMENT = "document", "Dokument"
    MARKETING = "marketing", "Zgoda marketingowa"
    FIELD = "field", "Pole formularza"


class ConsentRecord(TenantScopedModel):
    """The consent journal (ADR-073 §9): who saw which text of which version,
    and where. Append-only. It carries no personal data of its own — the
    subject is a customer's row, or, for somebody who is not a customer (an
    enquirer), only the source's reference."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="consents"
    )
    kind = models.CharField(max_length=16, choices=ConsentKind.choices)
    #: The text row the person saw; empty for a marketing or a field consent.
    document_text = models.ForeignKey(
        DocumentText, null=True, blank=True, on_delete=models.PROTECT, related_name="consents"
    )
    #: sha256 of what was shown: the row's text, or the consent's own wording.
    text_hash = models.CharField(max_length=64, blank=True)
    locale = models.CharField(max_length=10, blank=True)
    #: False withdraws an earlier consent of the same kind and source.
    granted = models.BooleanField(default=True)
    #: Where it happened, as a string (`booking.appointment`, `sites.inquiry`)
    #: and that record's id — never a foreign key to another module.
    source = models.CharField(max_length=64)
    source_reference = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind=ConsentKind.DOCUMENT, document_text__isnull=False)
                    | (~models.Q(kind=ConsentKind.DOCUMENT) & models.Q(document_text__isnull=True))
                ),
                name="customers_consent_document_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "customer"], name="customers_consent_customer_idx"
            ),
            models.Index(
                fields=["organization", "source", "source_reference"],
                name="customers_consent_source_idx",
            ),
        ]
        ordering = ("organization_id", "-created_at", "-id")


class DocumentRoute(models.Model):
    """Which company a document's public address belongs to. A lookup table
    without a tenant policy, read before the tenant is set (the pattern of
    booking's `PublicBookingRoute`): identifiers only, never a customer's or
    the document's content."""

    public_id = models.CharField(max_length=32, primary_key=True)
    organization_id = models.UUIDField()
    document_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.public_id
