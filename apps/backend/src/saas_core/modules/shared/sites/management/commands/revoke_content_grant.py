"""Stops one automation grant immediately.

The emergency brake of ADR-035 §4. A command rather than only a panel button
because the moment it is needed is the moment nobody wants to be looking for a
screen — the button arrives with the connections panel in W9.6.8, and this
stays as the thing an operator can reach from a terminal at three in the
morning.

Running it twice is safe: an already-revoked grant reports as such rather than
failing, because "make sure this is off" must not depend on remembering whether
somebody already ran it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.shared.sites.models import ContentAutomationGrant
from saas_core.modules.shared.sites.services import (
    AutomationGrantMissing,
    revoke_automation_grant,
)


class Command(BaseCommand):
    help = "Odwołuje grant automatyzacji treści ze skutkiem natychmiastowym."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--operator", required=True, help="E-mail operatora.")
        parser.add_argument("--grant", required=True, help="Identyfikator grantu.")
        parser.add_argument(
            "--reason",
            required=True,
            help="Dlaczego grant jest odwoływany. Trafia do audytu.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        operator = self._operator(str(options["operator"]))
        try:
            grant_id = UUID(str(options["grant"]))
        except (TypeError, ValueError) as error:
            raise CommandError("Nieprawidłowy identyfikator grantu.") from error

        # Read unscoped once to find which tenant the grant belongs to; the
        # revocation itself then runs inside that tenant's context, like every
        # other write in this module.
        grant = ContentAutomationGrant.all_objects.filter(pk=grant_id).first()
        if grant is None:
            raise CommandError("Grant nie istnieje.")
        already_revoked = grant.revoked_at is not None

        membership = Membership.objects.select_related("organization", "role").filter(
            organization_id=grant.organization_id,
            user=operator,
            status=MembershipStatus.ACTIVE,
        ).first()
        if membership is None:
            raise CommandError(
                "Operator nie ma aktywnego członkostwa w organizacji tego grantu."
            )

        with transaction.atomic():
            context = context_from_membership(membership)
            with activate_tenant_context(context):
                set_local_organization_id(context.organization_id)
                try:
                    revoke_automation_grant(
                        grant_id=grant_id, reason=str(options["reason"])
                    )
                except AutomationGrantMissing as error:
                    raise CommandError("Grant nie istnieje w tej organizacji.") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Grant {grant_id} "
                f"{'był już odwołany' if already_revoked else 'odwołany'}; "
                "klucz nie zapisze już żadnej zmiany."
            )
        )

    def _operator(self, email: str) -> User:
        normalized = User.objects.normalize_email(email)
        operator = User.objects.filter(email=normalized, is_active=True).first()
        if operator is None:
            raise CommandError(f"Operator {normalized} nie istnieje.")
        if not operator.is_staff:
            raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
        return operator
