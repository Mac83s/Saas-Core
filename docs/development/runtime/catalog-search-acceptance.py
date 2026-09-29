"""Catalogue search acceptance on a running local stack (ADR-064).

Runs inside the backend container, as the application role, so row-level
security applies — which the test suite cannot show:

    docker compose exec -T -e CATALOG_SEARCH_ACCEPTANCE=local backend \\
      python - < docs/development/runtime/catalog-search-acceptance.py

Creates once, then reuses, eight synthetic companies (slugs
`odbior-wyszukiwarki-*`), publishes them with the code the panel uses — inside
each tenant — and waits for the worker to index them. Then it checks that:

- the documents carry the description and service names, which the worker can
  only read with the tenant set (a missing SET LOCAL leaves them empty);
- Polish words find their entries: typos, no diacritics, ł, service names;
- a radius around a town returns the towns within it, with the distance.

`-e CATALOG_SEARCH_ACCEPTANCE_WITHDRAW=1` takes the entries out of the
catalogue again (the organizations stay). Exit status 1 when a check fails.
"""

import os
import sys
import time
import uuid

import django

assert os.environ.get("APP_ENV") == "local", "local stacks only"
assert os.environ.get("CATALOG_SEARCH_ACCEPTANCE") == "local"
django.setup()

from django.db import transaction  # noqa: E402
from django.utils.text import slugify  # noqa: E402

from saas_core.modules.core.organizations.context import set_local_organization_id  # noqa: E402
from saas_core.modules.core.organizations.models import Organization  # noqa: E402
from saas_core.modules.shared.booking.models import Service  # noqa: E402
from saas_core.modules.shared.profiles import search_engine, search_index  # noqa: E402
from saas_core.modules.shared.profiles.catalog import _place_entry  # noqa: E402
from saas_core.modules.shared.profiles.models import CatalogEntry, PublicProfile  # noqa: E402
from saas_core.modules.shared.profiles.public_views import search_catalog  # noqa: E402

PREFIX = "odbior-wyszukiwarki-"
COMPANIES = {
    "zlobek": (
        "Żłobek Promyk",
        "Opieka nad dziećmi od 1 do 3 lat",
        "lodz",
        "edukacja",
        [],
    ),
    "fryzjer": (
        "Studio Fryzjerskie Anna",
        "Koloryzacja i modelowanie",
        "mragowo",
        "uroda-i-zdrowie",
        [],
    ),
    "dentysta": (
        "Gabinet Stomatologiczny Uśmiech",
        "Leczenie zębów",
        "olsztyn",
        "uroda-i-zdrowie",
        ["Wybielanie"],
    ),
    "groomer": (
        "Salon Puszek",
        "Pielęgnacja zwierząt",
        "gizycko",
        "zwierzeta",
        ["Strzyżenie psa"],
    ),
    "racice": (
        "Nowak i Syn",
        "Bydło mleczne",
        "ketrzyn",
        "zwierzeta",
        ["Korekcja racic"],
    ),
    "weterynarz": (
        "Przychodnia Weterynaryjna Azor",
        "Psy i koty",
        "elk",
        "zwierzeta",
        [],
    ),
    "rolnik": (
        "Usługi Kowalski",
        "Łąki i zboże",
        "bartoszyce",
        "rolnictwo",
        ["Wynajem kombajnu"],
    ),
    "mechanik": (
        "Auto Serwis 24",
        "Naprawa samochodów",
        "olsztyn",
        "motoryzacja",
        ["Wymiana opon"],
    ),
}
QUERIES = [
    ("fryzer", "fryzjer"),
    ("zlobek", "zlobek"),
    ("lodz", "zlobek"),
    ("Łódź", "zlobek"),
    ("stomatlog", "dentysta"),
    ("strzyzenie psa", "groomer"),
    ("korekcja racic", "racice"),
    ("weterynaz", "weterynarz"),
    ("kombajn", "rolnik"),
    ("opony", "mechanik"),
]


def organization_id(key):
    # Derived, not looked up: the organization table is under RLS, so a lookup
    # by slug without a tenant finds nothing — which is the point of RLS.
    return uuid.uuid5(uuid.NAMESPACE_URL, PREFIX + key)


def ensure(key, name, headline, city, category, services):
    tenant = organization_id(key)
    with transaction.atomic():
        set_local_organization_id(tenant)
        if not Organization.objects.filter(pk=tenant).exists():
            Organization.objects.create(
                id=tenant, name=name, slug=PREFIX + key, status="active"
            )
        profile, _ = PublicProfile.all_objects.get_or_create(
            organization_id=tenant,
            subject_kind="organization",
            defaults={
                "display_name": name,
                "headline": headline,
                "bio": f"{name}: {headline.lower()}. Zapraszamy.",
                "city_slug": city,
                "category": category,
            },
        )
        for service in services:
            Service.all_objects.get_or_create(
                organization_id=tenant,
                public_slug=slugify(service),
                defaults={"name": service, "duration_minutes": 30},
            )
        _place_entry(profile, tenant)
    return str(tenant)


failures = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


if os.environ.get("CATALOG_SEARCH_ACCEPTANCE_WITHDRAW"):
    entries = CatalogEntry.all_objects.filter(
        organization_id__in=[organization_id(key) for key in COMPANIES]
    )
    removed = [entry.delete() for entry in entries]
    print(f"withdrawn: {len(removed)}")
    sys.exit(0)

engine = search_engine.engine()
check(engine is not None, "engine configured (SEARCH_URL, search_api_key)")
if engine is None:
    sys.exit(1)

ids = {key: ensure(key, *values) for key, values in COMPANIES.items()}
index = search_index.index_name()
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    documents = {
        document["id"]: document
        for document in engine.documents(index, ["id", "bio", "services"])
    }
    if set(ids.values()) <= set(documents):
        break
    time.sleep(1)
check(
    set(ids.values()) <= set(documents),
    f"worker indexed all {len(ids)} entries into {index}",
)

racice = documents.get(ids["racice"], {})
check(
    racice.get("services") == ["Korekcja racic"],
    "document has the tenant's service names (read under RLS)",
)
check(bool(racice.get("bio")), "document has the tenant's description (read under RLS)")

for query, expected in QUERIES:
    found = [item["slug"] for item in search_catalog(query=query)["items"][:3]]
    expected_slug = slugify(search_index.fold(COMPANIES[expected][0]))
    check(expected_slug in found, f"{query!r} -> {expected} (top 3: {found})")

around = search_catalog(city_slug="olsztyn", radius_km=60)["items"]
distances = {item["city_slug"]: item["distance_km"] for item in around}
check(
    distances.get("olsztyn") == 0.0 and 50 < (distances.get("mragowo") or 0) < 60,
    f"olsztyn +60 km: {distances}",
)

print(f"{len(failures)} failed")
sys.exit(1 if failures else 0)
