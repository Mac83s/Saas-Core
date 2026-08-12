from prometheus_client import Counter, Gauge

DELIVERY_RESULTS = Counter(
    "saas_core_notification_delivery_results_total",
    "Wyniki prób dostawy wiadomości i webhooków.",
    ("channel", "outcome"),
)
PROVIDER_STATUSES = Counter(
    "saas_core_notification_provider_status_total",
    "Statusy odebrane od providera e-mail.",
    ("status",),
)
SIGNATURE_FAILURES = Counter(
    "saas_core_integration_signature_failures_total",
    "Odrzucone podpisy webhooków przychodzących.",
    ("kind",),
)
PENDING_TASKS = Gauge(
    "saas_core_notification_pending_tasks",
    "Liczba niezakończonych tras odzyskiwania kolejki.",
    ("kind",),
)
