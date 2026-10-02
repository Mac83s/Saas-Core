"""What an operator sees about model calls, without content or tenants (ADR-068 pkt 8).

Every label is a bounded set: a task, an adapter, an outcome. No organization,
no model text — a metric label is stored forever and read by people who have
no business seeing which company asked what.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

CALLS = Counter(
    "saas_core_model_port_calls_total",
    "Wywołania portu modeli według zadania, adaptera i wyniku.",
    ("task", "adapter", "outcome"),
)
COST = Counter(
    "saas_core_model_port_cost_usd_micros_total",
    "Koszt wywołań znany od dostawcy albo policzony z cennika (mikro-USD).",
    ("task", "adapter"),
)
ESTIMATED = Counter(
    "saas_core_model_port_estimated_usd_micros_total",
    "Szacunek kosztu wywołań o nieznanym wyniku (mikro-USD).",
    ("task", "adapter"),
)
REFUSED_BEFORE_CALL = Counter(
    "saas_core_model_port_refused_before_call_total",
    "Wywołania zatrzymane przed dostawcą: bramki, budżet, reguły żądania.",
    ("task", "kind"),
)
LATENCY = Histogram(
    "saas_core_model_port_seconds",
    "Czas wywołania modelu.",
    ("task",),
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 18.0, 30.0, 60.0, 150.0),
)
