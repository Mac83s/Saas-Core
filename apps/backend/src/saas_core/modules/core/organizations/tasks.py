from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID, uuid7

from celery import shared_task
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F, Q

from saas_core.modules.core.identity.tokens import issue_bound_token
from saas_core.observability import correlation_id

from .context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
    require_tenant_context,
    set_local_organization_id,
)
from .email import InvitationEmailDeliveryError, get_invitation_email_sender
from .models import Invitation, Membership, MembershipStatus, Organization, OrganizationStatus

TENANT_TASK_CONTEXT_SALT = "saas-core.tenant-task-context.v1"
logger = logging.getLogger("saas_core.security")


class InvalidTenantTaskContext(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TenantTaskContract:
    version: int
    organization_id: str
    membership_id: str
    actor_id: str
    correlation_id: str
    causation_id: str
    principal_kind: str = "membership"
    role_key: str = ""
    permissions: tuple[str, ...] = ()


def issue_tenant_task_contract(*, causation_id: str) -> str:
    context = require_tenant_context()
    if not causation_id or len(causation_id) > 160:
        raise ValueError("causation_id musi mieć od 1 do 160 znaków.")
    contract = TenantTaskContract(
        version=2,
        organization_id=str(context.organization_id),
        membership_id=str(context.membership_id),
        actor_id=str(context.actor_id),
        correlation_id=correlation_id.get() or str(uuid7()),
        causation_id=causation_id,
        principal_kind=context.principal_kind,
        role_key=context.role_key,
        permissions=tuple(sorted(context.permissions)),
    )
    return signing.dumps(asdict(contract), salt=TENANT_TASK_CONTEXT_SALT, compress=True)


@contextmanager
def tenant_task_context(
    signed_contract: str,
    *,
    expected_causation_id: str | None = None,
) -> Iterator[TenantContext]:
    contract = _load_contract(signed_contract)
    if expected_causation_id is not None and not secrets.compare_digest(
        contract.causation_id,
        expected_causation_id,
    ):
        raise InvalidTenantTaskContext("Tenant task context nie pasuje do payloadu zadania.")
    correlation_token = correlation_id.set(contract.correlation_id)
    try:
        with transaction.atomic():
            if contract.principal_kind == "service":
                context = _service_context(contract)
                with activate_tenant_context(context):
                    set_local_organization_id(context.organization_id)
                    yield context
                return
            membership = _active_membership(
                organization_id=contract.organization_id,
                membership_id=contract.membership_id,
                actor_id=contract.actor_id,
            )
            if membership is None:
                raise InvalidTenantTaskContext(
                    "Tenant task context nie wskazuje aktywnego membership."
                )

            context = context_from_membership(membership)
            with activate_tenant_context(context):
                set_local_organization_id(context.organization_id)
                yield context
    finally:
        correlation_id.reset(correlation_token)


def _active_membership(
    *, organization_id: Any, membership_id: Any, actor_id: Any
) -> Membership | None:
    return (
        Membership.objects.select_for_update()
        .select_related("organization", "role")
        .filter(
            pk=membership_id,
            organization_id=organization_id,
            user_id=actor_id,
            status=MembershipStatus.ACTIVE,
            organization__status__in=[
                OrganizationStatus.ONBOARDING,
                OrganizationStatus.ACTIVE,
            ],
        )
        .filter(
            Q(role__organization__isnull=True)
            | Q(role__organization_id=F("organization_id"))
        )
        .first()
    )


@contextmanager
def deferred_tenant_context(
    *,
    organization_id: Any,
    membership_id: Any,
    actor_id: Any,
    causation_id: str,
) -> Iterator[TenantContext]:
    """Acts as a person who authorised something that runs much later.

    A signed task payload cannot serve here: it expires long before a
    publication scheduled for next week fires. The stored membership is asked
    again at the moment of running instead, so somebody who has since lost
    access does not get one more publication out of the queue.
    """
    correlation_token = correlation_id.set(str(uuid7()))
    try:
        with transaction.atomic():
            membership = _active_membership(
                organization_id=organization_id,
                membership_id=membership_id,
                actor_id=actor_id,
            )
            if membership is None:
                raise InvalidTenantTaskContext(
                    f"{causation_id}: membership nie jest już aktywny."
                )
            context = context_from_membership(membership)
            with activate_tenant_context(context):
                set_local_organization_id(context.organization_id)
                yield context
    finally:
        correlation_id.reset(correlation_token)


def _load_contract(signed_contract: str) -> TenantTaskContract:
    if not signed_contract:
        raise InvalidTenantTaskContext("Brak tenant task context.")
    try:
        payload = signing.loads(
            signed_contract,
            salt=TENANT_TASK_CONTEXT_SALT,
            max_age=settings.TENANT_TASK_CONTEXT_TTL_SECONDS,
        )
        if not isinstance(payload, dict):
            raise ValueError
        contract = TenantTaskContract(**_contract_fields(payload))
        if contract.version not in {1, 2}:
            raise ValueError
        UUID(contract.organization_id)
        UUID(contract.membership_id)
        UUID(contract.actor_id)
        UUID(contract.correlation_id)
        if not contract.causation_id or len(contract.causation_id) > 160:
            raise ValueError
        if contract.principal_kind not in {"membership", "service"}:
            raise ValueError
        return contract
    except (signing.BadSignature, TypeError, ValueError) as error:
        raise InvalidTenantTaskContext(
            "Tenant task context jest nieprawidłowy albo wygasł."
        ) from error


def _contract_fields(payload: dict[str, Any]) -> dict[str, Any]:
    base = {
        "version",
        "organization_id",
        "membership_id",
        "actor_id",
        "correlation_id",
        "causation_id",
    }
    extra = {"principal_kind", "role_key", "permissions"}
    if set(payload) not in {frozenset(base), frozenset(base | extra)}:
        raise ValueError
    values = {field: payload[field] for field in base}
    if extra <= set(payload):
        values.update({field: payload[field] for field in extra})
        if not isinstance(values["permissions"], (list, tuple)):
            raise ValueError
        values["permissions"] = tuple(values["permissions"])
    return values


def _service_context(contract: TenantTaskContract) -> TenantContext:
    allowed = {"booking.public.read", "booking.public.manage"}
    if (
        contract.version != 2
        or contract.role_key != "public_booking"
        or not set(contract.permissions) <= allowed
    ):
        raise InvalidTenantTaskContext("Service tenant context ma niedozwolony zakres.")
    if not Organization.objects.filter(
        pk=contract.organization_id,
        status__in=[OrganizationStatus.ONBOARDING, OrganizationStatus.ACTIVE],
    ).exists():
        raise InvalidTenantTaskContext("Service tenant context wskazuje nieaktywną organizację.")
    return TenantContext(
        organization_id=UUID(contract.organization_id),
        membership_id=UUID(contract.membership_id),
        actor_id=UUID(contract.actor_id),
        role_key=contract.role_key,
        permissions=frozenset(contract.permissions),
        principal_kind="service",
    )


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(InvitationEmailDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def send_organization_invitation(
    invitation_id: str,
    signed_tenant_context: str,
) -> None:
    try:
        with tenant_task_context(
            signed_tenant_context,
            expected_causation_id=invitation_id,
        ) as context:
            invitation = (
                Invitation.objects.select_related("organization", "role")
                .filter(pk=invitation_id, organization_id=context.organization_id)
                .first()
            )
            if invitation is None or not invitation.is_usable():
                return
            issued = issue_bound_token(
                purpose="organization-invitation",
                identifier=str(invitation.id),
            )
            if issued.digest != invitation.token_hash:
                return
            get_invitation_email_sender().send(
                email=invitation.email,
                locale=invitation.organization.default_locale,
                organization_name=invitation.organization.name,
                role_name=invitation.role.name,
                token=issued.value,
            )
    except InvalidTenantTaskContext:
        logger.warning(
            "organization_invitation_context_rejected",
            extra={"security_event": "organization.invitation_context_rejected"},
        )
