"""Brings companies to the current version of their plan (`plan_versions.py`).

    manage.py plan_version_move                          # who would move; writes nothing
    manage.py plan_version_move --plan pro               # the same, one plan
    manage.py plan_version_move --apply --operator <email> --reason "…"
    manage.py plan_version_move --organization <id>      # one company; writes nothing
    manage.py plan_version_move --organization <id> --apply --operator <email> \
        --reason "…" --accept-price-change --code <kod z aplikacji>

Without `--apply` nothing is written. A run moves only companies whose plan
costs the same in its current version; another price moves one named company,
with the operator's code from the authenticator app. Whatever the current
version takes away needs `--accept-losses`. A second run finds nothing to do.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from saas_core.modules.core.identity.mfa import InvalidMfaCode, MfaLocked, verify_totp_code
from saas_core.modules.core.identity.operators import (
    PLATFORM_ADMIN,
    operator_for_command,
    reason_of,
)
from saas_core.modules.core.identity.step_up import activate_step_up
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.models import Feature, Plan, QuotaDefinition
from saas_core.modules.shared.billing.plan_versions import (
    GRANTED,
    REFUSALS,
    SIMULATED,
    PlanMove,
    PlanMoveRefused,
    Price,
    apply_plan_move,
    pending_plan_moves,
    plan_move,
)
from saas_core.modules.shared.billing.tenant_scope import billing_tenant_scope

_INTERVALS = {"month": "miesiąc", "year": "rok"}
_PAYMENTS = {
    GRANTED: "plan nadany bez płatności",
    SIMULATED: "subskrypcja w symulatorze płatności",
    "stripe": "subskrypcja w Stripe",
}
#: What the operator can do about a refusal, where there is anything.
_HINTS = {
    "price_differs": "Użyj: --organization <id> --accept-price-change --code <kod z aplikacji>.",
    "losses": "Dodaj --accept-losses, jeśli firma ma to stracić.",
    "simulated_price_missing": "Uruchom najpierw: manage.py configure_simulated_prices.",
}
#: Said with another price, so nobody has to guess what it means for the company.
_PRICE_MEANS = {
    GRANTED: (
        "Firma nie płaci za ten plan (nadany bez płatności), więc jej rachunek się nie "
        "zmienia; karta planu pokaże nową cenę jako cenę jej wersji."
    ),
    SIMULATED: (
        "Od przeniesienia ceną firmy jest nowa cena. To symulator płatności: żadnych "
        "pieniędzy nie pobiera i u operatora płatności nic się nie zmienia."
    ),
}


class Command(BaseCommand):
    help = (
        "Przenosi firmy na bieżącą wersję ich planu. Bez --apply tylko pokazuje, kto by się "
        "przeniósł i co zyska albo straci."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Wykonaj przeniesienie. Bez tej flagi komenda niczego nie zapisuje.",
        )
        parser.add_argument("--plan", help="Tylko firmy na tym planie (klucz planu).")
        parser.add_argument(
            "--organization",
            help="Tylko ta firma (id). Jedyna droga, gdy bieżąca wersja ma inną cenę.",
        )
        parser.add_argument("--operator", help="Kto przenosi: operator poziomu 2 (e-mail).")
        parser.add_argument("--reason", help="Dlaczego; trafia do historii firmy.")
        parser.add_argument(
            "--accept-losses",
            action="store_true",
            help="Przenieś także wtedy, gdy bieżąca wersja odbiera funkcję albo obniża limit.",
        )
        parser.add_argument(
            "--accept-price-change",
            action="store_true",
            help="Przenieś firmę z --organization także przy innej cenie; wymaga --code.",
        )
        parser.add_argument(
            "--code",
            help="Bieżący kod z aplikacji uwierzytelniającej operatora (przy zmianie ceny).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization_id = self._organization(options["organization"])
        consents = {
            "accept_losses": bool(options["accept_losses"]),
            "accept_price_change": bool(options["accept_price_change"]),
        }
        if organization_id is None and consents["accept_price_change"]:
            raise CommandError(
                "--accept-price-change działa tylko z --organization: firmę, której plan ma "
                "w bieżącej wersji inną cenę, przenosi się pojedynczo."
            )
        if organization_id is not None and options["plan"]:
            raise CommandError("Podaj --organization albo --plan, nie oba naraz.")
        if options["plan"] and not Plan.objects.filter(key=options["plan"]).exists():
            raise CommandError(f"Nie ma planu o kluczu {options['plan']}.")

        if organization_id is not None:
            one = plan_move(organization_id)
            moves = [one] if one is not None else []
        else:
            moves = pending_plan_moves(plan_key=options["plan"])
        moves.sort(key=lambda move: (move.plan_key, move.organization_name.casefold()))
        names = _Names(moves)

        if not options["apply"]:
            self._preview(moves, names, consents, organization_id)
            return

        operator = operator_for_command(options["operator"], level=PLATFORM_ADMIN)
        reason = reason_of(options["reason"])
        step_up_at: int | None = None
        if any(not move.same_price and not move.blocked_by(**consents) for move in moves):
            # The step-up of this door: the code proves the operator is the one
            # running the command, as it would in the panel.
            if not options["code"]:
                raise CommandError(
                    "Zmiana ceny wymaga --code: bieżącego kodu z aplikacji uwierzytelniającej "
                    "operatora."
                )
            try:
                verify_totp_code(user=operator, code=str(options["code"]))
            except (InvalidMfaCode, MfaLocked) as error:
                raise CommandError(str(error.detail)) from error
            step_up_at = int(timezone.now().timestamp())

        moved = stayed = 0
        with activate_step_up(step_up_at):
            for move in moves:
                blocked = move.blocked_by(**consents)
                done: PlanMove | None = None
                if not blocked:
                    try:
                        done = apply_plan_move(
                            move.organization_id, operator=operator, reason=reason, **consents
                        )
                    except PlanMoveRefused as refused:
                        # The catalogue or the company changed since the list was read.
                        blocked = refused.reason
                if blocked:
                    stayed += 1
                    self._show(move, names)
                    self.stdout.write(self.style.WARNING(f"  → zostaje: {_refusal(blocked)}"))
                elif done is None:
                    self.stdout.write(f"{move.organization_name}: już na bieżącej wersji.")
                else:
                    moved += 1
                    self._show(done, names)
                    self.stdout.write(self.style.SUCCESS("  → przeniesiona"))
        if organization_id is not None and stayed:
            raise CommandError("Firmy nie przeniesiono.")
        if not moves:
            self.stdout.write(_nothing(organization_id))
        self.stdout.write(f"Przeniesione: {moved}, bez zmian: {stayed}.")

    def _organization(self, raw: str | None) -> UUID | None:
        if not raw:
            return None
        try:
            organization_id = UUID(raw)
        except ValueError as error:
            raise CommandError("--organization to id firmy (UUID).") from error
        # Inside the company's own tenant: under the application's role the
        # table answers with no rows until one is set, for a company that exists.
        with billing_tenant_scope(organization_id):
            if not Organization.objects.filter(pk=organization_id).exists():
                raise CommandError(f"Nie ma firmy o id {organization_id}.")
        return organization_id

    def _preview(
        self,
        moves: list[PlanMove],
        names: _Names,
        consents: dict[str, bool],
        organization_id: UUID | None,
    ) -> None:
        would_move = 0
        for move in moves:
            self._show(move, names)
            blocked = move.blocked_by(**consents)
            if blocked:
                self.stdout.write(self.style.WARNING(f"  → zostałaby: {_refusal(blocked)}"))
            else:
                would_move += 1
                self.stdout.write("  → zostałaby przeniesiona")
        if not moves:
            self.stdout.write(_nothing(organization_id))
        self.stdout.write(
            f"PODGLĄD — niczego nie zapisano. Do przeniesienia: {would_move}, "
            f"bez zmian: {len(moves) - would_move}. Wykonanie: dodaj --apply --operator "
            '<e-mail> --reason "…".'
        )

    def _show(self, move: PlanMove, names: _Names) -> None:
        write = self.stdout.write
        write(f"{move.organization_name} ({move.organization_id})")
        write(
            f"  plan {move.plan_key}: wersja {move.from_version} → {move.to_version}, "
            f"{_PAYMENTS[move.payment]}"
        )
        if move.same_price:
            write(f"  cena: bez zmian ({_money(move.price_from)})")
        else:
            write(f"  cena: {_money(move.price_from)} → {_money(move.price_to)}")
            if move.payment in _PRICE_MEANS:
                write(f"    {_PRICE_MEANS[move.payment]}")
        if move.gained_features:
            write("  zyskuje: " + "; ".join(names.feature(key) for key in move.gained_features))
        if move.raised_limits:
            write("  wyższe limity: " + names.limits(move.raised_limits))
        if move.lost_features:
            write("  TRACI: " + "; ".join(names.feature(key) for key in move.lost_features))
        if move.lowered_limits:
            write("  NIŻSZE LIMITY: " + names.limits(move.lowered_limits))
        if not (
            move.gained_features or move.raised_limits or move.lost_features or move.lowered_limits
        ):
            write("  funkcje i limity: bez zmian")


class _Names:
    """The catalogue's names of the features and limits the moves mention."""

    def __init__(self, moves: list[PlanMove]) -> None:
        features = {key for move in moves for key in (*move.gained_features, *move.lost_features)}
        limits = {key for move in moves for key in (*move.raised_limits, *move.lowered_limits)}
        self._features = dict(Feature.objects.filter(key__in=features).values_list("key", "name"))
        self._limits = dict(
            QuotaDefinition.objects.filter(key__in=limits).values_list("key", "name")
        )

    def feature(self, key: str) -> str:
        return _named(self._features, key)

    def limits(self, changes: dict[str, tuple[int | None, int | None]]) -> str:
        return "; ".join(
            f"{_named(self._limits, key)}: {_limit(now)} → {_limit(after)}"
            for key, (now, after) in changes.items()
        )


def _named(names: dict[str, str], key: str) -> str:
    return f"{names[key]} ({key})" if key in names else key


def _limit(value: int | None) -> str:
    return "brak" if value is None else str(value)


def _money(price: Price) -> str:
    amount = f"{price.unit_amount_minor / 100:.2f}".replace(".", ",")
    interval = _INTERVALS.get(price.billing_interval, price.billing_interval)
    return f"{amount} {price.currency} netto / {interval}"


def _refusal(code: str) -> str:
    hint = _HINTS.get(code)
    return f"{REFUSALS[code]} {hint}" if hint else REFUSALS[code]


def _nothing(organization_id: UUID | None) -> str:
    if organization_id is None:
        return "Żadna firma nie jest na starszej wersji swojego planu."
    return "Ta firma nie ma planu albo jest już na jego bieżącej wersji."
