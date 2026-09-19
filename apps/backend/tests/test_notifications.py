from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserMfaMethod, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.notifications.delivery import (
    DeliveryDeferred,
    deliver_email,
    process_provider_status,
)
from saas_core.modules.shared.notifications.models import (
    ApiKeyCredentialRoute,
    DeliveryStatus,
    EmailSuppression,
    NotificationMessage,
)
from saas_core.modules.shared.notifications.providers import ProviderMessage
from saas_core.modules.shared.notifications.security import validate_webhook_url
from saas_core.modules.shared.notifications.services import (
    MfaRequired,
    authenticate_api_key,
    ingest_provider_status,
    issue_api_key,
    queue_email,
    revoke_api_key,
    rotate_api_key,
    support_retry_message,
)

pytestmark = pytest.mark.django_db(transaction=True)


class FakeEmailProvider:
    def __init__(self, *, fail_before: bool = False, fail_after: bool = False) -> None:
        self.fail_before = fail_before
        self.fail_after = fail_after
        self.accepted: dict[str, ProviderMessage] = {}
        self.calls = 0

    def send(self, **kwargs: Any) -> ProviderMessage:
        self.calls += 1
        key = kwargs["idempotency_key"]
        if self.fail_before:
            raise RuntimeError("before accept")
        accepted = self.accepted.setdefault(key, ProviderMessage(f"provider:{key}", "sent"))
        if self.fail_after:
            raise RuntimeError("after accept")
        return accepted

    def status_for_idempotency_key(self, key: str) -> ProviderMessage | None:
        return self.accepted.get(key)


def membership(*, slug: str, role: str = "owner") -> Membership:
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug,
        slug=slug,
        status=OrganizationStatus.ACTIVE,
    )
    system_role, _ = Role.objects.get_or_create(
        key=role,
        organization=None,
        organization_type="",
        defaults={
            "name": role.title(),
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS[role]),
            "is_immutable": True,
        },
    )
    return Membership.objects.create(
        organization=organization,
        user=user,
        role=system_role,
    )


@contextmanager
def tenant(member: Membership):
    context = context_from_membership(member)
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        yield


def queued_message(member: Membership, monkeypatch: pytest.MonkeyPatch) -> NotificationMessage:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    with tenant(member):
        message, created = queue_email(
            recipient_email=member.user.email,
            recipient_user=member.user,
            template_key="system.activity",
            template_version=1,
            locale="pl",
            template_context={"display_name": "Jan", "message": "Zmiana konta"},
            idempotency_key="mail-1",
            causation_id="test-1",
        )
        assert created
    return message


def test_provider_failure_before_and_after_accept_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = membership(slug="email-failure")
    message = queued_message(member, monkeypatch)
    before = FakeEmailProvider(fail_before=True)
    with tenant(member), pytest.raises(DeliveryDeferred):
        deliver_email(message.id, provider=before)

    before.fail_before = False
    before.fail_after = True
    with tenant(member):
        delivered = deliver_email(message.id, provider=before)
        assert delivered.status == DeliveryStatus.SENT
        assert delivered.attempt_count == 2
    assert before.calls == 2
    assert len(before.accepted) == 1


def test_duplicate_and_reversed_provider_status_never_downgrades_bounce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = membership(slug="provider-status")
    message = queued_message(member, monkeypatch)
    provider = FakeEmailProvider()
    with tenant(member):
        deliver_email(message.id, provider=provider)
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.process_provider_status_task.delay",
        lambda *_args: None,
    )
    provider_id = next(iter(provider.accepted.values())).id
    bounced, created = ingest_provider_status(
        event_id="evt-bounce",
        provider_message_id=provider_id,
        status=DeliveryStatus.BOUNCED,
        payload_digest="a" * 64,
    )
    duplicate, duplicate_created = ingest_provider_status(
        event_id="evt-bounce",
        provider_message_id=provider_id,
        status=DeliveryStatus.BOUNCED,
        payload_digest="a" * 64,
    )
    assert created and not duplicate_created and bounced.pk == duplicate.pk
    ingest_provider_status(
        event_id="evt-delivered-late",
        provider_message_id=provider_id,
        status=DeliveryStatus.DELIVERED,
        payload_digest="b" * 64,
    )
    with tenant(member):
        process_provider_status("evt-bounce")
        process_provider_status("evt-delivered-late")
        message.refresh_from_db()
        assert message.status == DeliveryStatus.BOUNCED
        assert EmailSuppression.objects.filter(recipient_hash=message.recipient_hash).exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://localhost/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.4/hook",
        "http://example.com/hook",
    ],
)
def test_webhook_ssrf_rejects_local_metadata_private_and_http(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_webhook_url(url)


def test_webhook_ssrf_rechecks_all_dns_answers() -> None:
    def resolver(*_args: Any) -> list[tuple[Any, ...]]:
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.1", 443)),
        ]

    with pytest.raises(ValidationError):
        validate_webhook_url("https://hooks.example.test/events", resolver=resolver)


def test_api_key_rotation_and_revocation_invalidate_old_credentials() -> None:
    member = membership(slug="api-keys")
    with tenant(member):
        first = issue_api_key(name="automation", scopes=["notifications:read"])
    assert authenticate_api_key(first.secret, required_scope="notifications:read") is not None
    with tenant(member):
        rotated = rotate_api_key(key_id=first.api_key.id)
    assert authenticate_api_key(first.secret, required_scope="notifications:read") is None
    assert authenticate_api_key(rotated.secret, required_scope="notifications:read") is not None
    with tenant(member):
        revoke_api_key(key_id=rotated.api_key.id)
    assert authenticate_api_key(rotated.secret, required_scope="notifications:read") is None
    assert ApiKeyCredentialRoute.objects.filter(revoked_at__isnull=False).count() == 2


def test_support_requires_permission_and_mfa_and_retries_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = membership(slug="support-owner")
    message = queued_message(owner, monkeypatch)
    with tenant(owner):
        NotificationMessage.objects.filter(pk=message.id).update(
            status=DeliveryStatus.DEAD_LETTER,
            attempt_count=5,
            next_attempt_at=None,
        )
        with pytest.raises(MfaRequired):
            support_retry_message(message_id=message.id, reason="provider recovered")
    UserMfaMethod.objects.create(
        user=owner.user,
        secret_ciphertext="not-used-by-confirmation-check",
        confirmed_at=timezone.now(),
    )
    with tenant(owner):
        retried = support_retry_message(message_id=message.id, reason="provider recovered")
        assert retried.id == message.id
        assert retried.status == DeliveryStatus.QUEUED
        assert NotificationMessage.objects.count() == 1

    viewer = membership(slug="support-viewer", role="viewer")
    UserMfaMethod.objects.create(
        user=viewer.user,
        secret_ciphertext="not-used",
        confirmed_at=timezone.now(),
    )
    with tenant(viewer), pytest.raises(Exception) as denied:
        support_retry_message(message_id=message.id, reason="cross tenant")
    assert denied.value.__class__.__name__ == "OrganizationPermissionDenied"


def test_a_module_mails_its_own_template_with_a_file_resolved_at_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from saas_core.modules.shared.notifications.api import (  # noqa: PLC0415
        Attachment,
        EmailTemplate,
        register_attachment_resolver,
        register_email_template,
    )

    template = EmailTemplate(
        key="test.report",
        version=1,
        category="required",
        subjects={"pl": "Raport {farm}", "en": "Report {farm}"},
        bodies={"pl": "<p>Raport dla {farm}</p>", "en": "<p>Report for {farm}</p>"},
        allowed_context=frozenset({"farm"}),
    )
    register_email_template(template)
    register_email_template(template)  # the same again is fine
    with pytest.raises(ValueError, match="już istnieje"):
        register_email_template(
            EmailTemplate(
                key="test.report",
                version=1,
                category="marketing",
                subjects=template.subjects,
                bodies=template.bodies,
                allowed_context=template.allowed_context,
            )
        )
    files = {"ok": Attachment("raport.pdf", b"%PDF-1.4", "application/pdf")}
    register_attachment_resolver("test-file", lambda value: files[value])

    class Capturing(FakeEmailProvider):
        def send(self, **kwargs: Any) -> ProviderMessage:
            self.attachments = list(kwargs.get("attachments", ()))
            return super().send(**kwargs)

    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    member = membership(slug="zalacznik")
    with tenant(member):
        with pytest.raises(ValidationError):
            queue_email(
                recipient_email="farma@example.test",
                template_key="test.report",
                template_version=1,
                locale="pl",
                template_context={"farm": "Nowak"},
                idempotency_key="report-bad",
                causation_id="test",
                attachment_ref="unknown:1",
            )
        sent, _ = queue_email(
            recipient_email="farma@example.test",
            template_key="test.report",
            template_version=1,
            locale="pl",
            template_context={"farm": "Nowak"},
            idempotency_key="report-ok",
            causation_id="test",
            attachment_ref="test-file:ok",
        )
        missing, _ = queue_email(
            recipient_email="farma@example.test",
            template_key="test.report",
            template_version=1,
            locale="pl",
            template_context={"farm": "Nowak"},
            idempotency_key="report-missing",
            causation_id="test",
            attachment_ref="test-file:gone",
        )
    provider = Capturing()
    with tenant(member):
        assert deliver_email(sent.id, provider=provider).status == DeliveryStatus.SENT
        assert [a.filename for a in provider.attachments] == ["raport.pdf"]
        # A file that is not there is retried like a provider outage, never sent without it.
        with pytest.raises(DeliveryDeferred):
            deliver_email(missing.id, provider=provider)
        missing.refresh_from_db()
        assert missing.last_error_code == "attachment_unavailable"


def test_a_failed_attempt_survives_the_task_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry is raised after the task's tenant context commits the attempt."""
    from celery.exceptions import Retry  # noqa: PLC0415

    from saas_core.modules.shared.notifications.models import NotificationAttempt  # noqa: PLC0415
    from saas_core.modules.shared.notifications.tasks import deliver_email_task  # noqa: PLC0415

    member = membership(slug="ponowienie")
    message = queued_message(member, monkeypatch)
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.delivery.get_email_provider",
        lambda: FakeEmailProvider(fail_before=True),
    )
    with pytest.raises(Retry):
        deliver_email_task.run(str(message.id), message.signed_tenant_context)
    stored = NotificationMessage.all_objects.get(pk=message.id)
    assert (stored.attempt_count, stored.last_error_code) == (1, "provider_unavailable")
    assert NotificationAttempt.all_objects.filter(message_id=message.id).count() == 1


def test_a_problem_carries_the_code_the_module_raised() -> None:
    from rest_framework.exceptions import APIException, NotFound  # noqa: PLC0415

    from saas_core.http.exceptions import problem_code  # noqa: PLC0415

    assert problem_code(NotFound("Nie ma.", code="catalog_not_found")) == "catalog_not_found"
    assert problem_code(NotFound("Nie ma.")) == "not_found"
    explicit = APIException({"code": "x", "queue_mode": "herd"})
    explicit.problem_code = "visit_already_started"  # type: ignore[attr-defined]
    assert problem_code(explicit) == "visit_already_started"
