"""Who in the company receives a message from its site's contact form (R3a
W2; ADR-078). The owner by default, as before; or everyone who edits the
site — a front desk that answers enquiries. Each receives the mail in the
language of their own panel, never the page's."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    group_commands,
    register_command,
    register_setting_area,
    register_setting_group,
    setting,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

from .permissions import SITE_CONTENT_EDIT

RECIPIENTS = "sites.inquiries.recipients"

INQUIRIES_AREA = SettingArea(
    key="site-inquiries",
    title={"pl": "Zapytania ze strony", "en": "Website enquiries"},
    description={
        "pl": "Kto w firmie dostaje wiadomości z formularza kontaktowego na stronie.",
        "en": "Who in the company receives messages from the contact form on the site.",
    },
    order=65,
)

INQUIRIES = SettingGroup(
    key="sites.inquiries",
    module="shared.sites",
    title={"pl": "Odbiorcy zapytań", "en": "Who receives enquiries"},
    description={
        "pl": "Wiadomość z formularza kontaktowego na stronie firmy przychodzi e-mailem do "
        "tych osób, każdej w języku jej panelu.",
        "en": "A message from the contact form on the company's site comes by e-mail to "
        "these people, each in the language of their own panel.",
    },
    permission=SETTINGS_MANAGE,
    area="site-inquiries",
    commands=("sites.settings_inquiries.read@1", "sites.settings_inquiries.update@1"),
    settings=(
        SettingSpec(
            key=RECIPIENTS,
            type="enum",
            default="owner",
            scopes=("organization",),
            values=(
                ("owner", {"pl": "Właściciel", "en": "The owner"}),
                (
                    "editors",
                    {
                        "pl": "Każdy, kto redaguje stronę",
                        "en": "Everyone who edits the site",
                    },
                ),
            ),
            label={"pl": "Kto dostaje zapytania", "en": "Who receives enquiries"},
            help={
                "pl": "Np. recepcja, która odpowiada klientom — wystarczy, że ma prawo "
                "redagowania strony.",
                "en": "E.g. the front desk that answers customers — the right to edit the "
                "site is enough.",
            },
            model_description="Who gets the e-mail about a message from the site's contact "
            "form: the owner (the earliest active one), or everyone whose role may edit the "
            "site's content.",
        ),
    ),
)


def register_inquiry_settings() -> None:
    register_setting_area(INQUIRIES_AREA)
    register_setting_group(INQUIRIES)
    for command in group_commands(INQUIRIES):
        register_command(command)


def inquiry_recipients(organization_id: UUID) -> list[Any]:
    """The active accounts the company's choice names, the owner first — in
    the site's tenant."""
    memberships = list(
        Membership.objects.select_related("user", "role")
        .filter(
            organization_id=organization_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
        )
        .order_by("joined_at", "id")
    )
    owner = next((m for m in memberships if m.role.key == "owner"), None)
    chosen = [owner] if owner is not None else []
    if setting(RECIPIENTS) == "editors":
        chosen += [
            m
            for m in memberships
            if m is not owner and SITE_CONTENT_EDIT in (m.role.permissions or ())
        ]
    return [m.user for m in chosen]
