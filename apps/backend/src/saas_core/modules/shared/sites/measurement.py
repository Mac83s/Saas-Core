"""What a published site measures on its own: page views and inquiries (ADR-060).

Counted on the server and kept as numbers. The public renderer decides whether
a request was a person opening a page — a document GET, not a prefetch, not a
crawler — and says so with one header; nothing about the visitor reaches this
module, so nothing about a visitor is stored.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any
from uuid import UUID, uuid7

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    ContentEntryPublication,
    PageViewDay,
    PageViewKind,
    Publication,
    Site,
    SiteInquiry,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .publication_routing import PublicPage
from .services import SiteNotFound, assert_within_grant

logger = logging.getLogger("saas_core.sites")

#: Set by the public renderer on the one backend call that renders a page a
#: person opened. Anyone can also just open the page again, so the header
#: proves nothing a repeated visit would not; it only keeps crawlers, prefetch
#: and the panel out of the number.
COUNT_VIEW_HEADER = "HTTP_X_SAAS_CORE_COUNT_VIEW"

#: A quarter: two four-week windows around a change, with room for the lag of
#: the numbers they are compared with.
METRICS_MAX_DAYS = 92

_UPSERT = f"""
INSERT INTO {PageViewDay._meta.db_table}
    (id, organization_id, site_id, day, path, kind, publication_id, views)
VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
ON CONFLICT ON CONSTRAINT sites_pageviewday_key_uq
DO UPDATE SET views = {PageViewDay._meta.db_table}.views + 1
"""


class MetricsRangeInvalid(APIException):
    status_code = 400
    default_detail = f"Zakres dat musi mieć od 1 do {METRICS_MAX_DAYS} dni."
    default_code = "site_metrics_range_invalid"


def _kind(publication: Any) -> str:
    if isinstance(publication, Publication):
        return PageViewKind.PAGE
    if isinstance(publication, ContentEntryPublication):
        return PageViewKind.ENTRY
    return PageViewKind.COLLECTION


def record_page_view(page: PublicPage) -> None:
    """Adds one to today's count for this address and publication.

    One statement, so two visitors at the same moment cannot lose a view to
    each other. A failure is logged and swallowed: a number nobody reads until
    next week is not worth a page a visitor cannot open now.
    """
    if not settings.SITES_PAGE_VIEW_COUNTER_ENABLED:
        return
    try:
        with transaction.atomic():
            # The hostname named the tenant; the table forces row-level
            # security, so the setting goes first or the write is refused.
            set_local_organization_id(page.organization_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    _UPSERT,
                    [
                        uuid7(),
                        page.organization_id,
                        page.site_id,
                        timezone.now().astimezone(datetime.UTC).date(),
                        page.canonical_path,
                        _kind(page.publication),
                        page.publication.id,
                    ],
                )
    except DatabaseError:
        logger.warning("sites_page_view_not_counted", exc_info=True)


def read_site_metrics(
    *, site_id: UUID, since: datetime.date, until: datetime.date
) -> dict[str, Any]:
    """Daily views per address and publication, and inquiries per form.

    Inquiries are counted, never read: an automation measuring a change has
    no business with the inbox, and a count per form block is all a verdict
    on that form needs.
    """
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id, organization_id=context.organization_id
    ).exists():
        raise SiteNotFound
    # The whole site's numbers, so a grant for the whole site: one collection
    # does not stand for the pages around it.
    assert_within_grant(context, site_id=site_id)
    if not 0 <= (until - since).days < METRICS_MAX_DAYS:
        raise MetricsRangeInvalid
    views = PageViewDay.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        day__gte=since,
        day__lte=until,
    ).order_by("day", "path", "publication_id")
    start = datetime.datetime.combine(since, datetime.time.min, tzinfo=datetime.UTC)
    end = datetime.datetime.combine(
        until + datetime.timedelta(days=1), datetime.time.min, tzinfo=datetime.UTC
    )
    inquiries = (
        SiteInquiry.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
            created_at__gte=start,
            created_at__lt=end,
        )
        .annotate(day=TruncDate("created_at", tzinfo=datetime.UTC))
        .values("day", "page_path", "publication_id", "block_position")
        .annotate(count=Count("id"))
        .order_by("day", "page_path", "block_position")
    )
    return {
        "site_id": site_id,
        "since": since,
        "until": until,
        "counter_enabled": settings.SITES_PAGE_VIEW_COUNTER_ENABLED,
        "page_views": [
            {
                "day": row.day,
                "path": row.path,
                "kind": row.kind,
                "publication_id": row.publication_id,
                "views": row.views,
            }
            for row in views
        ],
        "inquiries": [
            {
                "day": row["day"],
                "path": row["page_path"],
                "publication_id": row["publication_id"],
                "block_position": row["block_position"],
                "count": row["count"],
            }
            for row in inquiries
        ],
    }
