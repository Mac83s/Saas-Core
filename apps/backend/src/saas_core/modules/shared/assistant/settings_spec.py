"""The assistant's limits and retention, as platform settings (ADR-078).

Class A: only the platform sets them (`platform_setting set <key> …`, later
the „Platforma” panel). The plan's conditions for opening the chat (decision
A1): a turn limit per person, a limit of new conversations per address, a
ceiling of model calls per turn and a daily ceiling for the whole deployment,
above which the chat sends people to the panel. The model port's own budgets
in dollars stand beside them (ADR-068 pkt 7).

Operator levels (S-T7): the two abuse throttles are level 1, so whoever is on
duty can tighten them at once; the model calls per message, the daily ceiling
(the platform's cost and what every company gets) and the retention (a legal
effect) are level 2. Values are read at use time, never kept in a constant.
"""

from __future__ import annotations

from saas_core.modules.core.organizations.api import SettingGroup, SettingSpec
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

TURNS_PER_MINUTE = SettingSpec(
    key="assistant.limits.turns_per_person_per_minute",
    type="int",
    default=12,
    minimum=1,
    maximum=120,
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Wiadomości do asystenta na osobę na minutę",
        "en": "Messages to the assistant per person per minute",
    },
    model_description="How many messages one person may send to the assistant within a "
    "minute; above it the chat asks them to wait.",
)
STARTS_PER_HOUR = SettingSpec(
    key="assistant.limits.conversation_starts_per_ip_per_hour",
    type="int",
    default=20,
    minimum=1,
    maximum=1000,
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Nowe rozmowy z jednego adresu na godzinę",
        "en": "New conversations from one address per hour",
    },
    model_description="How many conversations may be started from one network address "
    "within an hour.",
)
STEPS_PER_TURN = SettingSpec(
    key="assistant.limits.model_steps_per_turn",
    type="int",
    default=6,
    minimum=1,
    maximum=20,
    scopes=("platform",),
    label={
        "pl": "Wywołania modelu na jedną wiadomość",
        "en": "Model calls per message",
    },
    model_description="How many times the model may be called to answer one message "
    "(reading, proposing, reporting); above it the turn ends with what it has.",
)
DAILY_TURNS = SettingSpec(
    key="assistant.limits.daily_turns_ceiling",
    type="int",
    default=2000,
    minimum=0,
    maximum=1_000_000,
    scopes=("platform",),
    label={
        "pl": "Dzienny sufit wiadomości do asystenta",
        "en": "Daily ceiling of messages to the assistant",
    },
    model_description="Messages the whole deployment accepts in a day (UTC); above it the "
    "chat sends people to the panel. 0 closes the chat.",
)
RETENTION_DAYS = SettingSpec(
    key="assistant.retention.conversation_days",
    type="int",
    default=90,
    minimum=1,
    maximum=730,
    unit="day",
    scopes=("platform",),
    label={
        "pl": "Przechowywanie rozmów z asystentem (dni)",
        "en": "Keeping assistant conversations (days)",
    },
    model_description="Days a conversation is kept after its last message; then it is "
    "deleted with its transcript. Conversations also leave with their company.",
)

LIMITS = SettingGroup(
    key="assistant.limits",
    module="shared.assistant",
    title={"pl": "Limity asystenta", "en": "Assistant limits"},
    description={
        "pl": "Ile wiadomości i rozmów przyjmuje asystent.",
        "en": "How many messages and conversations the assistant accepts.",
    },
    # A platform group: no company writes it; the registry only needs a
    # permission some composed module declares.
    permission=SETTINGS_MANAGE,
    area="ai",
    settings=(TURNS_PER_MINUTE, STARTS_PER_HOUR, STEPS_PER_TURN, DAILY_TURNS),
)
RETENTION = SettingGroup(
    key="assistant.retention",
    module="shared.assistant",
    title={"pl": "Przechowywanie rozmów", "en": "Keeping conversations"},
    description={
        "pl": "Jak długo przechowujemy rozmowy z asystentem.",
        "en": "How long assistant conversations are kept.",
    },
    permission=SETTINGS_MANAGE,
    area="ai",
    settings=(RETENTION_DAYS,),
)
