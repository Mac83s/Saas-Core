from typing import Final

#: ADR-036 §3: one permission. Reading a profile needs nothing beyond belonging
#: to the organization — the content is meant for the public anyway — and there
#: is no entitlement of its own: what limits publication is the site plan.
PROFILES_MANAGE: Final = "profiles.manage"
