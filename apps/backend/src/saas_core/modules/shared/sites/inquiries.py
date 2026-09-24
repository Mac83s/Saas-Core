from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus, Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.modules.shared.billing.decisions import decide_feature
from saas_core.modules.shared.notifications.api import queue_email

from .inquiry_serializers import SiteInquirySubmitSerializer
from .models import Publication, Site, SiteInquiry, canonical_json_hash
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .publication_routing import PublicSiteMoved, PublicSiteNotFound, resolve_public_page
from .services import SiteNotFound, _idempotency_key, assert_person_required

INQUIRY_SUBMIT = "sites.inquiry.submit"

# Mirror of CONTACT_FORM_FIELDS in @saas-core/site-blocks (contact-form-block.ts):
# what each `contact` variant of core.contact_form requires. The name is always
# required by the serializer; a block without `contact` (v1) is "email".
CONTACT_FORM_FIELDS: dict[str, dict[str, str]] = {
    "email": {"email": "required", "phone": "optional", "message": "required"},
    "callback": {"email": "optional", "phone": "required", "message": "optional"},
    "full": {"email": "required", "phone": "required", "message": "required"},
    "email_only": {"email": "required", "phone": "hidden", "message": "required"},
}


def apply_contact_rules(block: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """The published block, not the visitor's browser, decides what is required."""
    block_data = block.get("data")
    mode = block_data.get("contact", "email") if isinstance(block_data, dict) else "email"
    rules = CONTACT_FORM_FIELDS.get(mode, CONTACT_FORM_FIELDS["email"])
    missing = {
        field: ["To pole jest wymagane."]
        for field, rule in rules.items()
        if rule == "required" and not data[field]
    }
    if missing:
        raise ValidationError(missing)
    # A form without a phone field cannot have sent one.
    return {**data, **{field: "" for field, rule in rules.items() if rule == "hidden"}}


class InquiryOriginDenied(PermissionDenied):
    default_code = "site_inquiry_origin_denied"
    default_detail = "Formularz należy wysłać z witryny, na której został opublikowany."


class InquiryPublicationChanged(APIException):
    status_code = 409
    default_code = "site_inquiry_publication_changed"
    default_detail = "Formularz zmienił się. Odśwież stronę przed wysłaniem."


class InquiryIdempotencyConflict(APIException):
    status_code = 409
    default_code = "site_inquiry_idempotency_conflict"
    default_detail = "Klucz wysyłki został już użyty do innego zgłoszenia."


class InquiryNotFound(NotFound):
    default_code = "site_inquiry_not_found"
    default_detail = "Zgłoszenie nie istnieje."


def validate_inquiry_origin(*, host: str, origin: str) -> None:
    try:
        value = urlsplit(origin)
        valid = (
            value.scheme in {"https", "http"}
            and value.netloc.lower() == host.lower()
            and value.username is None
            and value.password is None
            and value.path in {"", "/"}
            and not value.query
            and not value.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise InquiryOriginDenied


@contextmanager
def public_inquiry_context(organization_id: UUID) -> Iterator[TenantContext]:
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key="public_site_inquiry",
        permissions=frozenset({INQUIRY_SUBMIT}),
        principal_kind="service",
    )
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(organization_id)
        yield context


def submit_site_inquiry(
    *, host: str, origin: str, payload: dict[str, Any], idempotency_key: str
) -> tuple[SiteInquiry, bool]:
    """The hostname and current publication establish the destination, never body IDs."""
    validate_inquiry_origin(host=host, origin=origin)
    key = _idempotency_key(idempotency_key)
    serializer = SiteInquirySubmitSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        page = resolve_public_page(host=host, path=data["path"])
    except PublicSiteMoved as error:
        raise InquiryPublicationChanged from error
    if not isinstance(page.publication, Publication):
        raise PublicSiteNotFound
    organization_id = page.publication.organization_id
    request_hash = canonical_json_hash({**data, "publication_id": str(data["publication_id"])})
    with public_inquiry_context(organization_id):
        authorize_entitled(INQUIRY_SUBMIT, SITES_ENABLED)
        site = Site.all_objects.select_for_update().get(
            id=page.publication.site_id, organization_id=organization_id
        )
        existing = (
            SiteInquiry.all_objects.select_related("notification_message")
            .filter(organization_id=organization_id, site_id=site.id, idempotency_key=key)
            .first()
        )
        if existing:
            if existing.request_hash != request_hash:
                raise InquiryIdempotencyConflict
            return existing, False
        if (
            data["publication_id"] != page.publication.id
            or site.current_publication_id != page.publication.id
        ):
            raise InquiryPublicationChanged
        blocks = page.page.get("blocks", [])
        position = data["block_position"]
        if position >= len(blocks) or blocks[position].get("block_type") != "core.contact_form":
            raise PublicSiteNotFound
        data = apply_contact_rules(blocks[position], data)
        inquiry_id = uuid7()
        notification = None
        if decide_feature("notifications.enabled").allowed:
            owner = (
                Membership.objects.select_related("user")
                .filter(
                    organization_id=organization_id,
                    role__key="owner",
                    status=MembershipStatus.ACTIVE,
                    user__status=UserStatus.ACTIVE,
                )
                .order_by("joined_at", "id")
                .first()
            )
            if owner is not None:
                notification, _ = queue_email(
                    recipient_email=owner.user.email,
                    recipient_user=owner.user,
                    template_key="sites.inquiry_received",
                    template_version=1,
                    locale=page.locale,
                    template_context={
                        "site_name": site.name,
                        "name": data["name"],
                        # A call-back request may leave these empty.
                        "email": data["email"] or "—",
                        "phone": data["phone"] or "—",
                        "message": data["message"] or "—",
                        "reference": str(inquiry_id),
                    },
                    idempotency_key=f"site-inquiry:{inquiry_id}",
                    causation_id=f"site-inquiry:{inquiry_id}",
                )
        inquiry = SiteInquiry.all_objects.create(
            id=inquiry_id,
            organization_id=organization_id,
            site=site,
            publication=page.publication,
            page_path=page.canonical_path,
            block_position=position,
            name=data["name"],
            email=data["email"],
            phone=data["phone"],
            message=data["message"],
            notification_message=notification,
            idempotency_key=key,
            request_hash=request_hash,
        )
        record_audit(
            organization=Organization.objects.get(id=organization_id),
            action="sites.inquiry.received",
            actor=None,
            target_type="site_inquiry",
            target_id=inquiry.id,
            metadata={"site_id": str(site.id), "publication_id": str(page.publication.id)},
        )
        return inquiry, True


def inquiry_payload(inquiry: SiteInquiry) -> dict[str, Any]:
    return {
        "id": inquiry.id,
        "site_id": inquiry.site_id,
        "page_path": inquiry.page_path,
        "name": inquiry.name,
        "email": inquiry.email,
        "phone": inquiry.phone,
        "message": inquiry.message,
        "created_at": inquiry.created_at,
        "read_at": inquiry.read_at,
        "email_status": inquiry.notification_message.status
        if inquiry.notification_message
        else "unavailable",
    }


def list_site_inquiries(
    *, site_id: UUID, cursor: UUID | None = None, limit: int = 30
) -> dict[str, Any]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    assert_person_required(context, "site inquiries")
    if not Site.all_objects.filter(id=site_id, organization_id=context.organization_id).exists():
        raise SiteNotFound
    query = SiteInquiry.all_objects.select_related("notification_message").filter(
        organization_id=context.organization_id, site_id=site_id
    )
    if cursor:
        query = query.filter(id__lt=cursor)
    rows = list(query.order_by("-id")[: limit + 1])
    return {
        "items": [inquiry_payload(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


def get_site_inquiry(*, inquiry_id: UUID) -> SiteInquiry:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    assert_person_required(context, "site inquiries")
    inquiry = (
        SiteInquiry.all_objects.select_related("notification_message")
        .filter(id=inquiry_id, organization_id=context.organization_id)
        .first()
    )
    if inquiry is None:
        raise InquiryNotFound
    return inquiry


@transaction.atomic
def mark_site_inquiry_read(*, inquiry_id: UUID, idempotency_key: str) -> SiteInquiry:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "site inquiries")
    _idempotency_key(idempotency_key)
    inquiry = (
        SiteInquiry.all_objects.select_for_update(of=("self",))
        .select_related("notification_message")
        .filter(id=inquiry_id, organization_id=context.organization_id)
        .first()
    )
    if inquiry is None:
        raise InquiryNotFound
    if inquiry.read_at is None:
        inquiry.read_at = timezone.now()
        inquiry.save(update_fields=["read_at"])
        record_audit(
            organization=Organization.objects.get(id=context.organization_id),
            action="sites.inquiry.read",
            actor=User.objects.get(id=context.actor_id),
            target_type="site_inquiry",
            target_id=inquiry.id,
        )
    return inquiry
