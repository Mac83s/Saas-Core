import logging
import time

from prometheus_client import Gauge, start_http_server

from saas_core.config.celery import app

logger = logging.getLogger(__name__)
WORKERS = Gauge("saas_core_celery_workers", "Liczba odpowiadających workerów Celery.")
ACTIVE = Gauge("saas_core_celery_active_tasks", "Liczba aktywnych zadań Celery.")
RESERVED = Gauge("saas_core_celery_reserved_tasks", "Liczba zarezerwowanych zadań Celery.")
SCRAPE_OK = Gauge(
    "saas_core_celery_inspect_success",
    "Czy ostatni inspect Celery zakończył się poprawnie.",
)


def collect() -> None:
    inspector = app.control.inspect(timeout=5)
    stats = inspector.stats() or {}
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    WORKERS.set(len(stats))
    ACTIVE.set(sum(len(tasks) for tasks in active.values()))
    RESERVED.set(sum(len(tasks) for tasks in reserved.values()))
    SCRAPE_OK.set(1 if stats else 0)


def main() -> None:
    start_http_server(9808)
    logger.info("celery_metrics_started")
    while True:
        try:
            collect()
        except Exception:  # noqa: BLE001
            SCRAPE_OK.set(0)
            logger.exception("celery_metrics_collection_failed")
        time.sleep(15)


if __name__ == "__main__":
    main()
