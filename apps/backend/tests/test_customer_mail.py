"""Who a company's customers hear from, where their reply goes and the
company's note (owner answer 36a; ADR-078)."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.models import Organization, OrganizationSetting
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


def _note(text: str, locale: str = "pl") -> Any:
    return change_settings(
        GROUP,
        changes={"note": {locale: text}},
        expected_version=read_group(GROUP).version,
        idempotency_key=f"note-{locale}-{len(text)}",
    )


def _deliver(
    member: Any,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    key: str,
    locale: str = "pl",
    version: int = 1,
) -> Any:
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *_args: None,
    )
    contexts = {
        "booking.reminder": {"organization_name": "Studio", "starts_at": "jutro 10:00"},
        "system.activity": {"display_name": "Jan", "message": "Zmiana konta"},
    }
    if version == 3:
        # v3 (TL17c) carries the customer's link.
        contexts["booking.reminder"]["manage_url"] = "https://studio.test/de/booking/t0k3n"
    recorder = Recorder()
    with tenant(member):
        message, _ = queue_email(
            recipient_email="klient@example.test",
            template_key=template,
            template_version=version,
            locale=locale,
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


# --- one note per language (TL17c follow-up; ADR-078 localized_text) -------------------


def _speaks(member: Any, *locales: str) -> None:
    Organization.objects.filter(pk=member.organization_id).update(public_locales=list(locales))


def _german_reminder(member: Any, monkeypatch: pytest.MonkeyPatch, key: str) -> Any:
    return _deliver(
        member,
        monkeypatch,
        "booking.reminder",
        key,
        locale="de",
        version=3,
    )


def test_a_german_customer_gets_the_german_note_or_none_never_the_polish_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = membership("mail-languages")
    _speaks(member, "pl", "de")
    with tenant(member):
        _note("Prosimy o przybycie 10 minut wcześniej.")

    without = _german_reminder(member, monkeypatch, "de-1")
    assert without["html_body"].endswith("Termin ändern oder absagen</a></p>")
    assert "Prosimy" not in without["html_body"]

    with tenant(member):
        _note("Bitte kommen Sie 10 Minuten früher.", "de")
        # Setting German left Polish as it was.
        assert read_group(GROUP).values["note"].value == {
            "pl": "Prosimy o przybycie 10 minut wcześniej.",
            "de": "Bitte kommen Sie 10 Minuten früher.",
        }
    german = _german_reminder(member, monkeypatch, "de-2")
    assert german["html_body"].endswith("<p>Bitte kommen Sie 10 Minuten früher.</p>")
    assert "Prosimy" not in german["html_body"]


def test_an_empty_text_removes_one_language_and_reset_clears_the_note() -> None:
    member = membership("mail-merge")
    _speaks(member, "pl", "en")
    with tenant(member):
        _note("Do zobaczenia.")
        _note("See you soon.", "en")
        _note("", "pl")
        assert read_group(GROUP).values["note"].value == {"en": "See you soon."}
        change_settings(
            GROUP,
            changes={},
            reset=["note"],
            expected_version=read_group(GROUP).version,
            idempotency_key="note-reset",
        )
        cleared = read_group(GROUP).values["note"]
    assert (cleared.value, cleared.source) == ({}, "code")


def test_a_language_the_company_does_not_have_is_refused_in_the_preview_too() -> None:
    member = membership("mail-foreign")
    with tenant(member):
        for preview in (True, False):
            with pytest.raises(ValidationError) as refused:
                change_settings(
                    GROUP,
                    changes={"note": {"de": "Bis bald."}},
                    expected_version=read_group(GROUP).version,
                    idempotency_key="" if preview else "note-foreign",
                    preview=preview,
                )
            assert [error.code for error in refused.value.detail["note"]] == [  # type: ignore[call-overload,index]
                "locale_not_enabled"
            ]
        with pytest.raises(ValidationError) as unknown:
            _note("Hej.", "xx")
    assert [error.code for error in unknown.value.detail["note"]] == [  # type: ignore[call-overload,index]
        "locale_not_in_registry"
    ]


def test_a_removed_language_keeps_its_text_unused() -> None:
    member = membership("mail-shrink")
    _speaks(member, "pl", "de")
    with tenant(member):
        _note("Do zobaczenia.")
        _note("Bis bald.", "de")
    _speaks(member, "pl")
    with tenant(member):
        _note("Do zobaczenia wkrótce.")
        assert read_group(GROUP).values["note"].value == {
            "pl": "Do zobaczenia wkrótce.",
            "de": "Bis bald.",
        }


def test_a_note_saved_before_languages_reads_as_the_company_s_first_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No sweep across tenants: the old plain text is read as the first
    language's and becomes a map on the next save."""
    member = membership("mail-legacy")
    _speaks(member, "pl", "en")
    with tenant(member):
        OrganizationSetting.objects.create(
            organization=member.organization,
            key="notifications.customer_mail.note",
            value="Prosimy o punktualność.",
        )
        assert read_group(GROUP).values["note"].value == {"pl": "Prosimy o punktualność."}

    polish = _deliver(member, monkeypatch, "booking.reminder", "legacy-1")
    assert polish["html_body"].endswith("<p>Prosimy o punktualność.</p>")

    with tenant(member):
        _note("Please be on time.", "en")
        stored = OrganizationSetting.objects.get(
            organization=member.organization, key="notifications.customer_mail.note"
        ).value
    assert stored == {"pl": "Prosimy o punktualność.", "en": "Please be on time."}


def test_the_type_checks_each_text_and_keeps_only_languages_with_one() -> None:
    from saas_core.modules.core.organizations.settings_registry import check_value, setting_spec

    spec = setting_spec("notifications.customer_mail.note")

    assert check_value(spec, {"de": " Bis bald. ", "pl": "", "en": "   "}) == (
        {"de": "Bis bald."},
        "",
        "",
    )
    assert check_value(spec, "Do zobaczenia")[2] == "invalid"  # type: ignore[index]
    assert check_value(spec, {"pl": "x" * 301})[2] == "max_length"  # type: ignore[index]
    assert check_value(spec, {"en": "See www.studio.test"})[2] == "links"  # type: ignore[index]
    assert check_value(spec, {"xx": "Hej"})[2] == "locale_not_in_registry"  # type: ignore[index]


def test_the_api_and_the_command_take_a_text_per_language() -> None:
    from rest_framework.test import APIClient

    from saas_core.modules.core.identity.models import User
    from saas_core.modules.core.organizations.settings_commands import group_commands
    from saas_core.modules.core.organizations.settings_registry import (
        schema_entry,
        setting_group,
        setting_spec,
    )

    member = membership("mail-api")
    _speaks(member, "pl", "en")
    user = User.objects.get(pk=member.user_id)
    user.set_password("Bezpieczne-Haslo-2026!")
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "Bezpieczne-Haslo-2026!"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    token = client.cookies["csrftoken"].value
    base = f"/api/v1/organizations/current/settings/{GROUP}"

    read = client.get(f"{base}/").json()
    assert read["values"]["note"] == {}
    preview = client.post(
        f"{base}/preview/",
        {"expected_version": read["version"], "note": {"en": "See you soon."}},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert preview.status_code == 200
    assert preview.json()["changes"] == {"note": {"from": {}, "to": {"en": "See you soon."}}}
    saved = client.patch(
        f"{base}/",
        {"expected_version": read["version"], "note": {"en": "See you soon."}},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY="note-api-1",
    )
    assert saved.status_code == 200
    assert saved.json()["values"]["note"] == {"en": "See you soon."}

    assert schema_entry(setting_spec("notifications.customer_mail.note"))["type"] == (
        "localized_text"
    )
    _read, update = group_commands(setting_group(GROUP))
    note = update.input_schema["properties"]["note"]
    assert (update.name, update.version) == ("notifications.settings_customer_mail.update", 2)
    assert note["additionalProperties"] is False
    assert set(note["properties"]) == set(note["required"]) >= {"pl", "en", "de"}
    assert note["properties"]["de"]["type"] == ["string", "null"]
    assert note["properties"]["de"]["maxLength"] == 300


def test_a_text_per_language_is_the_company_s_alone_for_now() -> None:
    """The platform's dialog writes one string; a key of this type with a
    platform value would get a broken one (review by development-15)."""
    from dataclasses import replace

    from django.core.exceptions import ImproperlyConfigured

    from saas_core.modules.core.organizations.settings_registry import (
        register_setting_group,
        setting_group,
    )

    group = setting_group(GROUP)
    widened = replace(
        group,
        key="notifications.customer_mail_probe",
        commands=None,
        settings=(
            replace(
                group.settings[0],
                key="notifications.customer_mail_probe.note",
                scopes=("platform", "organization"),
            ),
        ),
    )
    with pytest.raises(ImproperlyConfigured, match="localized_text nie ma dziś wartości platformy"):
        register_setting_group(widened)


def test_a_change_naming_no_language_leaves_the_note_as_it_is() -> None:
    member = membership("mail-all-null")
    with tenant(member):
        before = read_group(GROUP)
        kept = change_settings(
            GROUP,
            changes={"note": {"pl": None, "en": None, "de": None}},
            expected_version=before.version,
            idempotency_key="note-nothing",
        )
        after = read_group(GROUP).values["note"]
    assert kept.changes == {}
    assert (after.value, after.source) == ({}, "code")
