"""What an operator needs to see about the connector, without seeing content.

Every label here is a bounded set: an event type, an outcome, a refusal code.
Nothing carries a tenant, a resource id, a path or a fragment of text — a
metric label is stored forever, scraped by anything on the network and read by
people who have no business seeing a customer's unpublished work. High
cardinality would also make the series unusable long before it leaked anything.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

CHANGE_SET_RESULTS = Counter(
    "saas_core_content_change_set_results_total",
    "Wyniki żądań Content Operations według rodzaju rozstrzygnięcia.",
    ("operation", "outcome"),
)
#: Refusals worth telling apart, because they mean different things to the
#: sender: a grant problem is permanent until somebody acts, a conflict means
#: recompute, a validation failure means the payload was wrong.
CHANGE_SET_REFUSALS = Counter(
    "saas_core_content_change_set_refusals_total",
    "Odrzucone żądania Content Operations według kodu Problem Details.",
    ("code",),
)
OUTBOX_EVENTS = Counter(
    "saas_core_content_outbox_events_total",
    "Zdarzenia treści zapisane do outboxu według typu.",
    ("event_type",),
)
CHANGE_SET_LATENCY = Histogram(
    "saas_core_content_change_set_seconds",
    "Czas rozstrzygnięcia żądania Content Operations.",
    ("operation",),
    # A connector's own timeout is the number that matters; buckets above it
    # only record how long we took to fail somebody who had already left.
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
