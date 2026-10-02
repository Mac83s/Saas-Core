"""What the profiles module says about the company's languages (ADR-071 pkt 4)."""

from __future__ import annotations

from uuid import UUID

from .models import PublicProfile

PROFILE_LOCALE_NOT_REMOVABLE = "profile_locale_not_removable"


def profile_locale_problems(
    organization_id: UUID, added: frozenset[str], removed: frozenset[str]
) -> dict[str, str]:
    """The language a profile is written in stays the company's while the
    profile is: its card would otherwise speak a language the company does not
    offer. Change the profile's language first."""
    del added
    return {
        code: PROFILE_LOCALE_NOT_REMOVABLE
        for code in PublicProfile.all_objects.filter(
            organization_id=organization_id, locale__in=removed
        ).values_list("locale", flat=True)
    }
