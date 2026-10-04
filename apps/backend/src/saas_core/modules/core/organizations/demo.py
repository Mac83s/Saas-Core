"""Demo data for a staging stack: `manage.py seed_demo` (Maciej, 30.09; the
stories of 04.10).

After logging in to a staging stack there should already be companies that
tell a story — a team, a calendar with a past and a future, orders in every
state, a published site — so that the product can be verified and shown
without clicking it together first. Core seeds what it owns — the accounts,
the organizations, who is in them with which role and the languages their
customers read — and then asks every composed module for its part through a
registry, the way erasure asks for its checks: core never imports a shared
module, and a product replaces the default scenario from its own vertical
module (ADR-049).

The seed writes through the modules' own services, the doors the panel and the
public forms use, so what it leaves is what the product itself could have
produced: with its history, its orders, its journal lines and its e-mails.
A past is made the same way — the service is called with the seed's own clock
set to the moment the thing happened (`DemoRun.clock`), never by writing a
date into a row.

Everything is idempotent. A second run finds what the first one made (an
organization by slug, an account by e-mail, a document by a stable id, a
booking by its idempotency key) and adds only what a new day needs: the
bookings of days that were not in reach last time, the next step of a story
whose time has come. Nothing is ever deleted.

What a product provides (package Y2 reads this):

- `register_demo_scenario(factory)` from its vertical module's `ready()` —
  its companies (`DemoOrganization`: accounts, type, plan, languages, the
  story in one line, the guide's click paths, each module's data under the
  part's name) instead of the Business ones;
- `register_demo_part(name, part, order=…, describe=…)` for what its own
  module seeds, run after the organizations exist;
- `register_demo_step(name, handler)` for what happens in a story at a moment
  of its own (a trim recorded on a farm visit…); the steps of the shared
  modules (`booking.visit`, `commerce.pay`…) are there to be used in the
  product's stories, played with `DemoRun.play`.
"""

from __future__ import annotations

import time as _time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.identity.step_up import activate_step_up

from .audit import record_audit
from .context import activate_tenant_context, context_from_membership, set_local_organization_id
from .models import (
    BillingProfile,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    WorkspaceKind,
)
from .pre_tenant import PRE_TENANT_DB
from .public_locales import change_public_locales, offered_locales
from .role_catalog import system_role
from .settings_service import settings_at_creation

#: Every demo account lives here, so no message can reach a real mailbox.
DEMO_EMAIL_SUFFIX = ".test"
_NAMESPACE = uuid.UUID("5f0c7c1e-3b1d-4d5e-9a2f-0d6e7c1b9a30")
_TICK = timedelta(microseconds=1)
#: What the audit says made a company: the mark a later run knows it by.
SEED = "seed_demo"
#: How long before the run a company the seed makes was founded: longer ago
#: than anything its stories tell, so its past has offers, prices and
#: documents to happen in.
FOUNDED = timedelta(days=900)


@dataclass(frozen=True)
class DemoPerson:
    email: str
    first_name: str
    last_name: str
    #: A system role key of the organization's type: owner, manager, staff…
    role: str = "owner"


@dataclass(frozen=True)
class DemoPath:
    """One click path of the presentation guide: what it shows, where it
    starts and what to click there."""

    title: str
    #: An address with the run's links in braces: `{panel}/panel/calendar`,
    #: `{site}/`, `{form}`. A path whose link the run does not have (the module
    #: is not composed, the step was skipped) is left out of the guide.
    where: str
    #: Which account walks it; empty — the owner.
    account: str = ""
    see: str = ""


@dataclass(frozen=True)
class DemoOrganization:
    #: How the scenario, `--scenario` and the modules' data refer to it.
    key: str
    name: str
    slug: str
    owner: DemoPerson
    members: tuple[DemoPerson, ...] = ()
    #: Empty: the profile's first organization type.
    organization_type: str = ""
    #: The plan the demo uses; billing gives it without a payment.
    plan: str = "pro"
    #: Each module's own data, under its part's name (`booking`, `inventory`…).
    data: Mapping[str, Any] = field(default_factory=dict)
    #: What this company shows, in one line (`--list`, the guide).
    story: str = ""
    #: Modules without which the company makes no sense: a profile that does
    #: not compose them leaves it out.
    requires: tuple[str, ...] = ()
    #: Companies that come with it whenever it is chosen (a farm with the
    #: company that trims there).
    needs: tuple[str, ...] = ()
    #: The languages its customers read, the first being its own; those the
    #: profile does not offer are left out, and a company never loses one.
    locales: tuple[str, ...] = ()
    #: The guide: click paths for a presentation, five by custom.
    paths: tuple[DemoPath, ...] = ()


@dataclass(frozen=True)
class DemoScenario:
    organizations: tuple[DemoOrganization, ...]
    #: Data between organizations (a farm linked to a company…), by part name.
    data: Mapping[str, Any] = field(default_factory=dict)
    #: The core's own Business scenario: modules fill in their default data.
    default: bool = False


@dataclass(frozen=True)
class DemoStep:
    """One thing that happens in a story, at its own moment."""

    at: datetime
    #: A registered step: `booking.visit`, `commerce.pay`…
    do: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class DemoStory:
    """What happens to one record over time — booked, paid, called off — told
    as steps. `key` is the same on every run (it names the booking's
    idempotency key); `memo` is what a step leaves for the next ones."""

    key: str
    steps: list[DemoStep]
    memo: dict[str, Any] = field(default_factory=dict)
    #: Why the rest of the story is not played (a taken slot, a refusal).
    stopped: str = ""


_STUDIO_PATHS = (
    DemoPath(
        "Kalendarz: wizyty z ostatnich dni, dzisiejsze i przyszłe; wakat w „Do przydzielenia”",
        "{panel}/panel/calendar",
        see="Wizyty, które minęły, i te przed nami; nieobecność klienta ma własny stan. "
        "„Sesja we dwoje” z jedną osobą czeka w „Do przydzielenia” (/panel/calendar/queue).",
    ),
    DemoPath(
        "Prośby o termin: oferta „na prośbę” czeka na odpowiedź firmy",
        "{panel}/panel/calendar/requests",
        see="Dzisiejsza prośba o „Warsztat indywidualny” czeka — „Przyjmij” albo „Odmów” "
        "z powodem; wcześniejsze są przyjęte, odrzucone albo wygasły.",
    ),
    DemoPath(
        "Zamówienia: czeka na przelew, opłacone na miejscu, anulowane, zwrócone",
        "{panel}/panel/orders",
        see="Filtr „Stan”. „Pakiet startowy” czeka na przelew z terminem; wizyty opłacone "
        "gotówką; jedno zamówienie odwołane i zwrócone, jedno z kwotą jeszcze do zwrotu.",
    ),
    DemoPath(
        "Usługi i cennik: cena sobotnia, dodatek, sposób zapłaty; „Wzorce ofert”",
        "{panel}/panel/settings/services",
        see="„Konsultacja” ma cenę podstawową i sobotnią oraz dodatek; „Warsztat "
        "indywidualny” jest na prośbę, „Pakiet startowy” z przelewem z góry. W „Wzorcach "
        "ofert” (/panel/settings/services/presets) firma jest zapisana na „Zajęcia grupowe”.",
    ),
    DemoPath(
        "Prywatność: podgląd usuwania danych klientów po czasie (wyłączone); dziennik zgód",
        "{panel}/panel/settings/privacy",
        see="Wybierz „Po 12 miesiącach” i „Zapisz zmiany”: okno mówi, ilu dawnych klientów "
        "dotyczy zmiana; „Anuluj” niczego nie zapisuje. Dziennik zgód: "
        "/panel/settings/consents; klient zanonimizowany: /panel/settings/customer-removal.",
    ),
)
_LODGING_PATHS = (
    DemoPath(
        "Strona firmy z szablonu „Noclegi”: domki, cena „od”, mapa, kalendarz, języki",
        "{site}/",
        see="Przełącznik języków; „Sprawdź wolny termin” prowadzi do formularza z wybranym "
        "terminem; strona domku pod /stay/…, regulamin pod /documents/booking-terms/.",
    ),
    DemoPath(
        "Rezerwacja pobytu przez gościa: cena, przedpłata, regulamin i zgody",
        "{form}",
        see="Wybierz domek i termin: cena za noc z osobami w cenie, rabat za długość, "
        "sprzątanie, kaucja osobno; przedpłata 30% przelewem; regulamin do zaznaczenia.",
    ),
    DemoPath(
        "Obłożenie: kto mieszka dziś, przyjazdy i wyjazdy, pobyty przed nami",
        "{panel}/panel/calendar/occupancy",
        see="Cztery jednostki w wierszach; pobyty z ostatnich tygodni, trwające i przyszłe.",
    ),
    DemoPath(
        "Zamówienia pobytów: czeka na przelew, opłacone częściowo, opłacone, zwrócone, "
        "anulowane z rozliczeniem",
        "{panel}/panel/orders",
        see="W zamówieniu: wpłaty, termin dopłaty, a przy odwołanym — ile wraca do gościa "
        "według progów zwrotu i ile już zwrócono.",
    ),
    DemoPath(
        "Dokumenty dla klientów i dziennik zgód; tłumaczenie „Do akceptacji”",
        "{panel}/panel/settings/documents",
        see="Regulamin w językach firmy, polityka prywatności po polsku; jej wersje w innych "
        "językach czekają w /panel/sites/translations/review tam, gdzie działa atrapa modelu. "
        "Dziennik zgód: /panel/settings/consents.",
    ),
)
_RENTAL_PATHS = (
    DemoPath(
        "Strona wypożyczalni: kajaki z ceną za dzień i kalendarz wolnych dni",
        "{site}/",
        see="Lista jednostek, kalendarz wolnych dni, mapa; przycisk prowadzi do formularza.",
    ),
    DemoPath(
        "Rezerwacja kajaka na dni: cena za dzień, kaucja, płatność na miejscu",
        "{form}",
        see="Wybierz dni: cena za dzień, kaucja pokazana osobno (wraca przy zwrocie sprzętu).",
    ),
    DemoPath(
        "Obłożenie: kajaki na wodzie dziś i rezerwacje na kolejne dni",
        "{panel}/panel/calendar/occupancy",
        see="Trzy kajaki jednej puli i canoe; wypożyczenia z ostatnich dni i przyszłe.",
    ),
    DemoPath(
        "Zamówienia: opłacone gotówką przy wydaniu sprzętu, do zapłaty, anulowane",
        "{panel}/panel/orders",
        see="Wypożyczenia opłacone na miejscu i te, które dopiero będą.",
    ),
    DemoPath(
        "Jednostki i cennik: pula kajaków, cena za dzień, kaucja",
        "{panel}/panel/settings/services",
        see="Oferta z wzorca „Wypożyczalnia”, rezerwowana od–do na dni; pula „Kajak 2-os.”.",
    ),
)


def default_scenario() -> DemoScenario:
    """Business: three companies, each telling another story. The studio has
    the same people as the local stack's accounts (KONTA-TESTOWE.md)."""
    return DemoScenario(
        organizations=(
            DemoOrganization(
                key="studio",
                name="Studio Testowe",
                slug="studio-testowe",
                owner=DemoPerson("wlasciciel@saas.test", "Anna", "Właścicielka"),
                members=(
                    DemoPerson("kierownik@saas.test", "Marek", "Kierownik", "manager"),
                    DemoPerson("pracownik@saas.test", "Paweł", "Pracownik", "staff"),
                ),
                story="Firma z wizytami: zespół, cennik z ceną sobotnią i dodatkiem, płatność "
                "na miejscu, oferta „na prośbę” i oferta z przelewem z góry, magazyn.",
                locales=("pl", "en"),
                paths=_STUDIO_PATHS,
            ),
            DemoOrganization(
                key="domki",
                name="Domki nad Jeziorem",
                slug="domki-nad-jeziorem",
                owner=DemoPerson("domki@saas.test", "Dorota", "Jeziorna"),
                members=(
                    DemoPerson("recepcja.domki@saas.test", "Robert", "Recepcjonista", "manager"),
                ),
                story="Noclegi: pobyt z wzorca, domki ze zdjęciami i wyposażeniem, sezony, "
                "cena za noc z osobami w cenie i rabatem za długość, przedpłata, progi "
                "zwrotu, strona z szablonu „Noclegi” w trzech językach.",
                requires=("shared.booking",),
                locales=("pl", "en", "de"),
                paths=_LODGING_PATHS,
            ),
            DemoOrganization(
                key="kajaki",
                name="Kajaki Krutynia",
                slug="kajaki-krutynia",
                owner=DemoPerson("kajaki@saas.test", "Krzysztof", "Wioślarz"),
                story="Wypożyczalnia: kajaki rezerwowane na dni, pula jednostek, kaucja, "
                "płatność na miejscu.",
                requires=("shared.booking",),
                locales=("pl", "en"),
                paths=_RENTAL_PATHS,
            ),
        ),
        default=True,
    )


DemoPart = Callable[["DemoRun"], None]
#: What a part would make for one company, for `--list`: lines, without writing.
DemoDescribe = Callable[[DemoScenario, DemoOrganization], Sequence[str]]
DemoStepHandler = Callable[["DemoRun", str, DemoStory, DemoStep], None]
_scenario: Callable[[], DemoScenario] = default_scenario
_parts: dict[str, tuple[int, DemoPart, DemoDescribe | None]] = {}
_steps: dict[str, DemoStepHandler] = {}


def register_demo_scenario(factory: Callable[[], DemoScenario]) -> None:
    """A product's vertical module replaces the Business scenario (last wins:
    verticals are ready after the shared modules)."""
    global _scenario
    _scenario = factory


def register_demo_part(
    name: str, part: DemoPart, *, order: int, describe: DemoDescribe | None = None
) -> None:
    """A module's share of the demo, run in `order` after the organizations
    exist; `describe` says what it would make for a company (`--list`)."""
    _parts[name] = (order, part, describe)


def register_demo_step(name: str, handler: DemoStepHandler) -> None:
    """What a story's step named `name` does (`DemoRun.play`). The handler is
    called at the step's moment, inside the company's transaction, and must
    find by itself what an earlier run already did."""
    _steps[name] = handler


def demo_scenario() -> DemoScenario:
    return _scenario()


def demo_parts() -> list[tuple[str, DemoPart]]:
    return [(name, part) for name, (_order, part, _describe) in _ordered_parts()]


def _ordered_parts() -> list[tuple[str, tuple[int, DemoPart, DemoDescribe | None]]]:
    return sorted(_parts.items(), key=lambda item: item[1][0])


class DemoRequest(HttpRequest):
    """What services that take a request read from it: who acts."""

    def __init__(self, user: User) -> None:
        super().__init__()
        self.user = user
        self.META["REMOTE_ADDR"] = "127.0.0.1"


class DemoRun:
    """One run of the seed: the scenario, what exists, and how to act in it."""

    def __init__(
        self,
        scenario: DemoScenario,
        *,
        password: str,
        log: Callable[[str], None],
        now: datetime | None = None,
    ) -> None:
        self.scenario = scenario
        self.password = password
        self.log = log
        self.now = now or timezone.now()
        self.organizations: dict[str, Organization] = {}
        self.users: dict[str, User] = {}
        #: When each company the seed made — in this run or an earlier one —
        #: was founded; a company somebody else made is not here.
        self.founded: dict[str, datetime] = {}
        #: Addresses the guide's paths are built from, per company: `panel`
        #: here, `site` and `form` from the modules that make them.
        self.links: dict[str, dict[str, str]] = {}
        #: A part's own notes for a later part, by any key it chooses.
        self.memo: dict[str, Any] = {}

    # --- lookups ---------------------------------------------------------------

    def spec(self, key: str) -> DemoOrganization:
        return next(item for item in self.scenario.organizations if item.key == key)

    def data(self, key: str, part: str) -> Any:
        return self.spec(key).data.get(part)

    def user(self, email: str) -> User:
        return self.users[email.lower()]

    def leave_out(self, key: str, reason: str) -> None:
        """A part found that the seed must not go on with this company (its
        own settings would make the seed's writes do more than the seed
        means): the parts after it no longer see it."""
        spec = self.spec(key)
        self.scenario = DemoScenario(
            organizations=tuple(item for item in self.scenario.organizations if item.key != key),
            data=self.scenario.data,
            default=self.scenario.default,
        )
        self.log(f"! {spec.name} pominięta: {reason}")

    def stable_id(self, *parts: str) -> uuid.UUID:
        """The same id on every run, so a retried write finds its first result."""
        return uuid.uuid5(_NAMESPACE, "|".join(parts))

    def zone(self, key: str) -> ZoneInfo:
        return ZoneInfo(self.organizations[key].timezone)

    def day(self, key: str, offset: int) -> date:
        return self.now.astimezone(self.zone(key)).date() + timedelta(days=offset)

    def at(self, key: str, offset: int, clock: str) -> datetime:
        return self.on(key, self.day(key, offset), clock)

    def on(self, key: str, day: date, clock: str) -> datetime:
        """`clock` („10:30”) of `day` in the company's time zone."""
        hours, minutes = (int(part) for part in clock.split(":"))
        return datetime.combine(day, time(hours, minutes), tzinfo=self.zone(key))

    # --- acting ----------------------------------------------------------------

    @contextmanager
    def clock(self, moment: datetime) -> Iterator[None]:
        """Inside, this process reads `moment` as now — and goes on from it, so
        two rows written one after another keep their order. The way a demo
        gets a past through the services themselves: a visit of last week is
        booked the week before it and paid on its day. Only the seed's own
        process is affected; every reading goes through `timezone.now`."""
        started, original, last = _time.monotonic(), timezone.now, moment - _TICK

        def reading() -> datetime:
            nonlocal last
            last = max(moment + timedelta(seconds=_time.monotonic() - started), last + _TICK)
            return last

        setattr(timezone, "now", reading)  # noqa: B010 — a function, replaced on purpose
        try:
            yield
        finally:
            setattr(timezone, "now", original)  # noqa: B010

    @contextmanager
    def setting_up(self, key: str) -> Iterator[None]:
        """The moment a company's own setup is written at: just after its
        founding for a company the seed made — its languages, bank account,
        documents, offers and prices are then there for the bookings of its
        past — and now for a company somebody else made."""
        founded = self.founded.get(key)
        if founded is None:
            yield
            return
        with self.clock(founded + timedelta(hours=1)):
            yield

    @contextmanager
    def acting(
        self, key: str, email: str | None = None, *, step_up: bool = False
    ) -> Iterator[DemoRequest]:
        """Inside the organization as one of its people, in one transaction,
        with the same tenant context a request of theirs would carry.
        `step_up`: as after the second factor a person confirms before a
        guarded change (a legal document, the bank account)."""
        organization = self.organizations[key]
        user = self.user(email or self.spec(key).owner.email)
        with transaction.atomic():
            set_local_organization_id(organization.id)
            membership = Membership.objects.select_related("role").get(
                organization=organization, user=user, status=MembershipStatus.ACTIVE
            )
            with (
                activate_tenant_context(context_from_membership(membership)),
                activate_step_up(int(timezone.now().timestamp()) if step_up else None),
            ):
                yield DemoRequest(user)

    def play(self, key: str, stories: Sequence[DemoStory]) -> None:
        """Every step of `stories` whose moment has come, oldest first, each at
        its own moment (`clock`). In one transaction for the company, so no
        scheduled task meets a story half told — a booking made „three days
        ago” and not yet paid „two days ago”; a step that is refused undoes
        only itself and ends its story."""
        due = sorted(
            (
                (step.at, order, index, story, step)
                for order, story in enumerate(stories)
                for index, step in enumerate(story.steps)
                if step.at <= self.now
            ),
            key=lambda item: item[:3],
        )
        organization = self.organizations[key]
        with transaction.atomic():
            set_local_organization_id(organization.id)
            for _at, _order, _index, story, step in due:
                handler = _steps.get(step.do)
                if story.stopped or handler is None:
                    # A step of a module the profile does not compose is not
                    # played; the story goes on without it.
                    continue
                try:
                    with self.clock(step.at), transaction.atomic():
                        handler(self, key, story, step)
                except (APIException, DjangoValidationError) as error:
                    detail = getattr(error, "detail", None) or getattr(error, "messages", error)
                    story.stopped = str(detail)
                    self.log(f"! {story.key} · {step.do} ({step.at:%d.%m %H:%M}): {detail}")
                # A handler's `transaction.atomic` may have reset the tenant
                # of the outer transaction's later statements: say it again.
                set_local_organization_id(organization.id)

    # --- core's own part -------------------------------------------------------

    def seed_people_and_organizations(self) -> None:
        for spec in self.scenario.organizations:
            owner = self._account(spec.owner)
            organization = self._organization(spec, owner)
            self.organizations[spec.key] = organization
            self.links[spec.key] = {"panel": panel_address()}
            for person in spec.members:
                self._membership(organization, self._account(person), person.role)

    def _account(self, person: DemoPerson) -> User:
        email = User.objects.normalize_email(person.email).lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email, self.password, status=UserStatus.ACTIVE)
            self.log(f"+ konto {email}")
        else:
            # An operator's or a switched-off account is never a demo account,
            # whatever its address: the seed does not reset it.
            if user.is_staff or user.is_superuser or user.status != UserStatus.ACTIVE:
                raise ValueError(
                    f"Konto {email} nie jest kontem demo (operator albo wyłączone); "
                    "dane demo go nie zmienią."
                )
            # Demo accounts only (.test): the password is the one given now.
            user.set_password(self.password)
        user.first_name, user.last_name = person.first_name, person.last_name
        user.save()
        self.users[email] = user
        return user

    def _organization(self, spec: DemoOrganization, owner: User) -> Organization:
        found = Organization.objects.using(PRE_TENANT_DB).filter(slug=spec.slug).first()
        if found is not None:
            # A slug is not a claim: the seed goes on only with an organization
            # its own scenario's owner owns, never takes over somebody else's.
            with transaction.atomic():
                set_local_organization_id(found.id)
                owned = Membership.objects.filter(
                    organization=found, user=owner, role__key="owner"
                ).exists()
                # A company an earlier run of the seed made was founded then:
                # what a later run still has to set up is set up at that time.
                seeded = OrganizationAuditEntry.objects.filter(
                    organization=found,
                    action=OrganizationAuditAction.ORGANIZATION_CREATED,
                    metadata__source=SEED,
                ).exists()
            if not owned:
                raise ValueError(
                    f"Organizacja {spec.slug} należy do kogoś innego niż {owner.email}; "
                    "dane demo jej nie przejmą."
                )
            if seeded:
                self.founded[spec.key] = found.created_at
            self.log(f"= organizacja {spec.name}")
            # Read again inside the company: the row found by slug came
            # through the pre-tenant door and would be read and saved there.
            return self._inside(found.id)
        organization_type = spec.organization_type or str(settings.DEFAULT_ORGANIZATION_TYPE)
        organization = Organization(
            name=spec.name,
            slug=spec.slug,
            workspace_kind=WorkspaceKind.BUSINESS,
            organization_type=organization_type,
            default_locale="pl",
            timezone="Europe/Warsaw",
            currency="PLN",
        )
        organization.full_clean(validate_unique=False)
        founded = self.now - FOUNDED
        with self.clock(founded), transaction.atomic():
            set_local_organization_id(organization.id)
            organization.save()
            BillingProfile.objects.create(organization=organization)
            settings_at_creation(organization)
            Membership.objects.create(
                organization=organization,
                user=owner,
                role=system_role(organization_type, "owner"),
            )
            record_audit(
                organization=organization,
                action=OrganizationAuditAction.ORGANIZATION_CREATED,
                actor=owner,
                target_type="organization",
                target_id=organization.id,
                metadata={"source": SEED},
            )
        self.founded[spec.key] = founded
        self.log(f"+ organizacja {spec.name} ({organization_type})")
        return organization

    def _inside(self, organization_id: uuid.UUID) -> Organization:
        with transaction.atomic():
            set_local_organization_id(organization_id)
            return Organization.objects.get(pk=organization_id)

    def reload(self, key: str) -> Organization:
        """The company as it is now, after a part changed it (its languages)."""
        self.organizations[key] = self._inside(self.organizations[key].id)
        return self.organizations[key]

    def _membership(self, organization: Organization, user: User, role_key: str) -> None:
        with transaction.atomic():
            set_local_organization_id(organization.id)
            membership = Membership.objects.filter(organization=organization, user=user).first()
            if membership is not None:
                return
            Membership.objects.create(
                organization=organization,
                user=user,
                role=system_role(organization.organization_type, role_key),
            )
        self.log(f"+ {user.email} w {organization.name} jako {role_key}")

    # --- the guide -------------------------------------------------------------

    def guide(self) -> list[str]:
        """The accounts and, per company, its click paths with this stack's
        addresses — what the command prints last."""
        lines = ["Konta (jedno hasło, podane przy uruchomieniu):"]
        for spec in self.scenario.organizations:
            people = ", ".join(
                f"{person.email} ({person.role})" for person in (spec.owner, *spec.members)
            )
            lines.append(f"  {spec.name}: {people}")
        for spec in self.scenario.organizations:
            lines.append(f"{spec.name} — {spec.story}" if spec.story else spec.name)
            number = 0
            for path in spec.paths:
                try:
                    where = path.where.format(**self.links[spec.key])
                except KeyError:
                    continue
                number += 1
                account = path.account or spec.owner.email
                lines.append(f"  {number}. {path.title}")
                lines.append(f"     {where}  [{account}]")
                if path.see:
                    lines.append(f"     {path.see}")
        return lines


def seed_languages(run: DemoRun) -> None:
    """The languages a company's customers read (`DemoOrganization.locales`):
    those the profile offers are added after the ones the company has; a
    company with them already is left alone, and none is ever taken away."""
    offered = set(offered_locales())
    for spec in run.scenario.organizations:
        current = run.reload(spec.key)
        wanted = [code for code in spec.locales if code in offered]
        missing = [code for code in wanted if code not in current.public_locales]
        if not missing:
            continue
        try:
            with run.setting_up(spec.key), run.acting(spec.key):
                change_public_locales(
                    locales=[*current.public_locales, *missing],
                    expected_version=current.public_locales_version,
                    idempotency_key=str(
                        run.stable_id("locales", spec.slug, *current.public_locales, *missing)
                    ),
                )
        except (APIException, DjangoValidationError) as error:
            run.log(f"! języki {spec.name}: {getattr(error, 'detail', error)}")
            continue
        run.log(f"+ języki {spec.name}: {', '.join(run.reload(spec.key).public_locales)}")


#: After the plan (10), which bounds how many languages a company may have.
_parts["organizations.languages"] = (15, seed_languages, None)


def assert_demo_emails(scenario: DemoScenario) -> None:
    """A demo account never has a real address: no message can reach anybody."""
    for spec in scenario.organizations:
        for person in (spec.owner, *spec.members):
            if not person.email.lower().endswith(DEMO_EMAIL_SUFFIX):
                raise ValueError(f"Konto demo {person.email} musi mieć adres w domenie .test.")


def chosen_scenario(
    only: Sequence[str] | None = None, *, log: Callable[[str], None]
) -> DemoScenario:
    """The scenario with the companies asked for (`--scenario`), or all of it:
    each with the companies it needs, and without those the profile cannot
    hold — a module they require is not composed."""
    scenario = demo_scenario()
    known = {spec.key: spec for spec in scenario.organizations}
    if only:
        unknown = sorted(set(only) - set(known))
        if unknown:
            raise ValueError(f"Nie ma scenariusza {', '.join(unknown)}; są: {', '.join(known)}.")
        wanted = set(only)
        while True:
            more = {need for key in wanted for need in known[key].needs if need in known}
            if more <= wanted:
                break
            wanted |= more
    else:
        wanted = set(known)
    active = set(settings.ACTIVE_MODULES)
    kept = []
    for spec in scenario.organizations:
        if spec.key not in wanted:
            continue
        missing = [module for module in spec.requires if module not in active]
        if missing:
            log(f"= {spec.name} pominięta: profil nie składa {', '.join(missing)}")
            continue
        kept.append(spec)
    return DemoScenario(organizations=tuple(kept), data=scenario.data, default=scenario.default)


def describe_demo(only: Sequence[str] | None = None) -> list[str]:
    """What a run would make, without making it (`--list`)."""
    lines: list[str] = []
    scenario = chosen_scenario(only, log=lines.append)
    assert_demo_emails(scenario)
    for spec in scenario.organizations:
        kind = spec.organization_type or str(settings.DEFAULT_ORGANIZATION_TYPE)
        lines.append(f"{spec.key}: {spec.name} (slug {spec.slug}, typ {kind}, plan {spec.plan})")
        if spec.story:
            lines.append(f"  {spec.story}")
        for person in (spec.owner, *spec.members):
            lines.append(
                f"  konto {person.email} — {person.first_name} {person.last_name}, {person.role}"
            )
        if spec.locales:
            lines.append(f"  języki: {', '.join(spec.locales)} (te, które ma profil)")
        for name, (_order, _part, describe) in _ordered_parts():
            if describe is None:
                continue
            for line in describe(scenario, spec):
                lines.append(f"  {name}: {line}")
    return lines


def run_demo(
    *,
    password: str,
    log: Callable[[str], None],
    now: datetime | None = None,
    only: Sequence[str] | None = None,
) -> DemoRun:
    scenario = chosen_scenario(only, log=log)
    assert_demo_emails(scenario)
    run = DemoRun(scenario, password=password, log=log, now=now)
    # A run told what time it is (a test) reads that time everywhere.
    with run.clock(run.now) if now is not None else _real_clock():
        run.seed_people_and_organizations()
        for name, part in demo_parts():
            log(f"— {name}")
            part(run)
    return run


@contextmanager
def _real_clock() -> Iterator[None]:
    yield


def panel_address() -> str:
    """Where the panel and the booking forms answer on this stack: the
    platform's own domain, else the address the mails link to."""
    domain = str(getattr(settings, "SITES_PLATFORM_DOMAIN", "") or "")
    return site_address(domain) if domain else str(settings.FRONTEND_BASE_URL).rstrip("/")


def site_address(hostname: str) -> str:
    """Where a browser opens a company's site on this stack: the scheme the
    stack serves sites with and, on a developer's machine, the port its panel
    answers at (a VPS stack is named `local` too, but serves https)."""
    port = urlsplit(str(settings.FRONTEND_BASE_URL)).port
    scheme = settings.PUBLIC_SITE_SCHEME
    suffix = f":{port}" if scheme == "http" and port else ""
    return f"{scheme}://{hostname}{suffix}"
