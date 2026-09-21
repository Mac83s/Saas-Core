from typing import Final

#: ADR-036 §3: one permission. Reading a profile needs nothing beyond belonging
#: to the organization — the content is meant for the public anyway.
PROFILES_MANAGE: Final = "profiles.manage"

#: ADR-053 §9. The profile is the floor of the offer, so every plan grants this;
#: it exists so that publishing into the public catalogue is gated by the same
#: mechanism as every other feature, not so that some plan can be sold without
#: a business card.
PROFILES_ENABLED: Final = "profiles.enabled"
