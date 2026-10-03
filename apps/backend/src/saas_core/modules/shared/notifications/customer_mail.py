"""Who a company's customers hear from, and where their reply goes (owner
answer 36a, 2026-10-03; ADR-078).

A mail to a customer leaves from the platform's address — the domain the
platform signs for — under the company's name, and a reply goes to the
company: the e-mail its business card shows, else its owner's. The company may
add a short note in its own words; plain text without links, and never the
customer's data, because the same note goes to every customer.

The business card belongs to Profiles, which is built on this module, so
Profiles hands its name and e-mail in (`register_customer_sender`) instead of
being imported here.
"""

from __future__ import annotations

from collections.abc import Callable
from email.utils import formataddr, parseaddr
from html import escape
from uuid import UUID

from django.conf import settings

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
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

NOTE = "notifications.customer_mail.note"

#: Its own area of „Ustawienia”, on the generic page: a company without the
#: calendar still writes to its customers.
CUSTOMER_EMAILS_AREA = SettingArea(
    key="customer-emails",
    title={"pl": "E-maile do klientów", "en": "E-mails to customers"},
    description={
        "pl": "Pod jaką nazwą klienci dostają e-maile, dokąd trafia ich odpowiedź i tekst "
        "firmy na końcu każdego e-maila.",
        "en": "The name customers' e-mails come under, where their reply goes and the "
        "company's note at the end of each one.",
    },
    order=60,
)

CUSTOMER_MAIL = SettingGroup(
    key="notifications.customer_mail",
    module="shared.notifications",
    title={"pl": "E-maile do klientów", "en": "E-mails to customers"},
    description={
        "pl": "E-maile do klientów wychodzą pod nazwą firmy, a odpowiedź klienta trafia na "
        "e-mail z wizytówki firmy albo właściciela. Możesz dopisać krótki tekst od siebie.",
        "en": "E-mails to customers go out under the company's name, and a customer's reply "
        "goes to the e-mail on the company's business card, else the owner's. You may add "
        "a short note of your own.",
    },
    permission=SETTINGS_MANAGE,
    area="customer-emails",
    commands=(
        "notifications.settings_customer_mail.read@1",
        "notifications.settings_customer_mail.update@1",
    ),
    settings=(
        SettingSpec(
            key=NOTE,
            type="text",
            default="",
            max_length=300,
            no_links=True,
            scopes=("organization",),
            label={"pl": "Tekst firmy w e-mailach", "en": "The company's note in e-mails"},
            help={
                "pl": "Np. „Prosimy o przybycie 10 minut wcześniej.” Bez linków i adresów; ten "
                "sam tekst dostaje każdy klient, więc nie wpisuj danych żadnego z nich.",
                "en": "E.g. “Please come 10 minutes early.” No links or addresses; every "
                "customer gets the same note, so put no customer's details in it.",
            },
            model_description="A short plain-text note (up to 300 characters, no links or "
            "addresses) added at the end of every e-mail to the company's customers. The "
            "same for every customer: never a customer's data. Empty: no note.",
        ),
    ),
)

#: The company's name and e-mail as its business card shows them ("" where it
#: shows none); Profiles registers it.
_card: Callable[[UUID], tuple[str, str]] | None = None


def register_customer_sender(card: Callable[[UUID], tuple[str, str]]) -> None:
    global _card  # noqa: PLW0603 - one source, set once at start
    _card = card


def register_customer_mail() -> None:
    register_setting_area(CUSTOMER_EMAILS_AREA)
    register_setting_group(CUSTOMER_MAIL)
    for command in group_commands(CUSTOMER_MAIL):
        register_command(command)


def customer_sender(organization_id: UUID) -> tuple[str, str]:
    """The From and the Reply-To of a mail to this company's customers, in its
    tenant: the company's name at the platform's address; its card's e-mail,
    else its owner's, else none."""
    name, reply_to = _card(organization_id) if _card is not None else ("", "")
    if not name:
        name = Organization.objects.get(pk=organization_id).name
    if not reply_to:
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
        reply_to = owner.user.email if owner is not None else ""
    address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    # One line: a name is a header, and a header must not break.
    return formataddr((" ".join(name.split()), address)), reply_to


def with_company_note(html_body: str, organization_id: UUID) -> str:
    """The body with the company's note under it, escaped, as it reads now."""
    note = str(setting(NOTE, organization_id=organization_id) or "")
    if not note:
        return html_body
    lines = "<br>".join(escape(line) for line in note.splitlines())
    return f"{html_body}<p>{lines}</p>"
