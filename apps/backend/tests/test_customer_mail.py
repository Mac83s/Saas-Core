"""Who a company's customers hear from, where their reply goes and the
company's note (owner answer 36a; ADR-078)."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.notifications.delivery import deliver_email
from saas_core.modules.shared.notifications.providers import ProviderMessage
from saas_core.modules.shared.notifications.services import queue_email
from saas_core.modules.shared.profiles.models import PublicProfile
from test_booking import membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)

GROUP = "notifications.customer_mail"


class Recorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, **kwargs: Any) -> ProviderMessage:
        self.sent.append(kwargs)
        return ProviderMessage(f"provider:{kwargs['idempotency_key']}", "sent")

    def status_for_idempotency_key(self, key: str) -> ProviderMessage | None:
        return None


def _note(text: str) -> Any:
    return change_settings(
        GROUP,
        changes={"note": text},
        expected_version=read_group(GROUP).version,
        idempotency_key=f"note-{len(text)}",
    )


def _deliver(member: Any, monkeypatch: pytest.MonkeyPatch, template: str, key: str) -> Any:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    contexts = {
        "booking.reminder": {"organization_name": "Studio", "starts_at": "jutro 10:00"},
        "system.activity": {"display_name": "Jan", "message": "Zmiana konta"},
    }
    recorder = Recorder()
    with tenant(member):
        message, _ = queue_email(
            recipient_email="klient@example.test",
            template_key=template,
            template_version=1,
            locale="pl",
            template_context=contexts[template],
            idempotency_key=key,
            causation_id=key,
        )
        deliver_email(message.id, provider=recorder)
    return recorder.sent[0]


def test_a_customer_hears_from_the_company_and_replies_to_its_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = membership("mail-card")
    PublicProfile.all_objects.create(
        organization=member.organization,
        subject_kind="organization",
        display_name="Studio Urody, Ewa",
        contact_email="recepcja@studio.test",
    )

    sent = _deliver(member, monkeypatch, "booking.reminder", "card-1")

    # The company's name at the platform's own address, quoted where it must be.
    assert sent["from_email"] == '"Studio Urody, Ewa" <noreply@localhost>'
    assert sent["reply_to"] == "recepcja@studio.test"


def test_without_a_card_the_reply_goes_to_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    member = membership("mail-owner")

    sent = _deliver(member, monkeypatch, "booking.reminder", "owner-1")

    assert sent["from_email"] == "mail-owner <noreply@localhost>"
    assert sent["reply_to"] == "mail-owner@example.test"


def test_the_company_s_note_ends_its_customers_mail_and_never_a_staff_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = membership("mail-note")
    with tenant(member):
        _note("Prosimy o przybycie 10 min wcześniej, m.in. z dowodem.\n<Do zobaczenia>")

    customer = _deliver(member, monkeypatch, "booking.reminder", "note-1")
    staff = _deliver(member, monkeypatch, "system.activity", "note-2")

    assert customer["html_body"].endswith(
        "<p>Prosimy o przybycie 10 min wcześniej, m.in. z dowodem.<br>&lt;Do zobaczenia&gt;</p>"
    )
    assert "Prosimy" not in staff["html_body"]
    assert staff["from_email"] == ""
    assert staff["reply_to"] == ""


@pytest.mark.parametrize(
    "text",
    ["Zapisy: https://studio.test", "Zajrzyj na www.studio.test", "Pisz: biuro@studio.pl"],
)
def test_the_note_takes_no_links(text: str) -> None:
    member = membership("mail-links")
    with tenant(member), pytest.raises(ValidationError) as refused:
        _note(text)

    assert [error.code for error in refused.value.detail["note"]] == ["links"]  # type: ignore[call-overload,index]
