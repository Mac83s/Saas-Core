"""The map of the addresses a site had before it was built here (ADR-077):
one 308 to where the content answers today, or 410 — and never ahead of
anything the site itself answers."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.sites.models import Page, SiteOldAddress
from saas_core.modules.shared.sites.old_addresses import OLD_ADDRESSES_LOADED, address_key
from test_platform_workspace import confirm_mfa, operator
from test_sites_api import csrf_value
from test_sites_blog_languages import Blog, _feed, _get, _translate_entry
from test_sites_section_addresses import _moved, _rename

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture
def staff() -> str:
    person = operator(email="mapa@example.test")
    confirm_mfa(person)
    return str(person.email)


def _load(blog: Blog, staff: str, tmp_path: Path, rows: str, **options: Any) -> str:
    file = tmp_path / "old.csv"
    file.write_text(rows, encoding="utf-8")
    out = StringIO()
    call_command(
        "load_old_addresses", host=blog.host, csv=str(file), operator=staff, stdout=out, **options
    )
    return out.getvalue()


def _rules(blog: Blog) -> dict[str, str]:
    return {
        rule.key: rule.to_path or rule.outcome
        for rule in SiteOldAddress.all_objects.filter(site_id=blog.site_id)
    }


def _verdict(host: str, path: str) -> dict[str, Any]:
    return dict(APIClient().get("/api/v1/public/site/gone/", {"path": path}, HTTP_HOST=host).data)


def test_an_old_address_has_one_spelling() -> None:
    assert address_key("/Rasy-Psow/Owczarek/") == "/rasy-psow/owczarek"
    assert address_key("/a/b?page=2#top") == "/a/b"
    assert address_key("//a//b//") == "/a/b"
    assert address_key("/") == "/"
    # Percent-encoded, typed, upper-cased and encoded twice: one address.
    cyrillic = "/ru/породы-собак"
    encoded = "/ru/%D0%BF%D0%BE%D1%80%D0%BE%D0%B4%D1%8B-%D1%81%D0%BE%D0%B1%D0%B0%D0%BA"
    assert address_key(encoded) == cyrillic
    assert address_key("/RU/ПОРОДЫ-собак/") == cyrillic
    assert address_key(encoded.replace("%", "%25")) == cyrillic
    # A letter and its accent typed apart (NFD) are the letter (NFC).
    assert address_key("/ru/й") == address_key("/ru/й") == "/ru/й"
    # Lower-cased, not case-folded: two addresses stay two.
    assert address_key("/straße") != address_key("/strasse")


def test_an_old_address_leads_in_one_step_to_where_its_content_answers_today(
    staff: str, tmp_path: Path
) -> None:
    blog = Blog("old-map-moved")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    _load(
        blog,
        staff,
        tmp_path,
        "old_path,new_path\n"
        # A language prefix the site no longer uses is part of the old address.
        "/pl/oferta-stara,/oferta\n"
        "/ru/%D0%BF%D0%BE%D1%80%D0%BE%D0%B4%D1%8B,/blog/wpis-jeden/\n"
        "https://old.example.test/EN/Old-Post/?utm=1,/en/blog/in-english/\n",
    )
    host = blog.host

    # However the visitor spells it — and straight to the canonical address,
    # though the file named the target without its slash.
    for asked in ("/pl/oferta-stara", "/pl/oferta-stara/", "/PL/Oferta-Stara"):
        assert _moved(host, asked) == (308, "/oferta/"), asked
    assert _moved(host, "/ru/породы/") == (308, "/blog/wpis-jeden/")
    assert _moved(host, "/en/old-post") == (308, "/en/blog/in-english/")

    # The page is renamed later: the old address goes straight to today's.
    offer = Page.all_objects.get(site_id=blog.site_id, key="oferta")
    renamed = blog.client.put(
        f"/api/v1/sites/pages/{offer.id}/url/",
        {"locale": "pl", "slug": "uslugi", "reason": "Nowa nazwa oferty."},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
    )
    assert renamed.status_code == 200, renamed.data
    blog.publish("renamed-page")
    assert _moved(host, "/oferta/") == (308, "/uslugi/")
    assert _moved(host, "/pl/oferta-stara") == (308, "/uslugi/")

    # So is the section: no stop under its former name.
    assert _rename(blog, "poradnik", reason="Nowa nazwa działu.").status_code == 200
    assert _moved(host, "/ru/породы") == (308, "/poradnik/wpis-jeden/")
    assert _moved(host, "/en/old-post") == (308, "/en/poradnik/in-english/")


def test_a_gone_address_answers_410_in_the_language_it_was_asked_in(
    staff: str, tmp_path: Path
) -> None:
    blog = Blog("old-map-gone")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    assert _verdict(blog.host, "/ogloszenia") == {"rules": False, "gone": False}
    _load(blog, staff, tmp_path, "/ogloszenia,gone\n/en/listings/,GONE\n/pl/konto,410\n")

    polish = _get(blog.host, "/Ogloszenia/")
    assert polish.status_code == 410
    assert (polish.data["code"], polish.data["locale"], polish.data["home_path"]) == (
        "public_site_gone",
        "pl",
        "/",
    )
    english = _get(blog.host, "/EN/Listings")
    assert (english.status_code, english.data["locale"], english.data["home_path"]) == (
        410,
        "en",
        "/en/",
    )
    # What the proxy asks first, because a page cannot answer 410 itself.
    assert _verdict(blog.host, "/en/Listings/") == {
        "rules": True,
        "gone": True,
        "locale": "en",
        "home_path": "/en/",
    }
    assert _verdict(blog.host, "/oferta/") == {"rules": True, "gone": False}
    assert _verdict("nobody.example.test", "/ogloszenia") == {"rules": False, "gone": False}
    # Not pages: no sitemap entry, and so no hreflang, names them.
    sitemap = _feed(blog.host, "sitemap.xml").content.decode()
    assert "ogloszenia" not in sitemap and "listings" not in sitemap


def test_whatever_the_site_answers_wins_over_a_rule(staff: str, tmp_path: Path) -> None:
    blog = Blog("old-map-live")
    _load(
        blog,
        staff,
        tmp_path,
        "/oferta,gone\n/blog/,/\n/stare,/nie-ma-takiej/\n/pierwszy,/drugi/\n/drugi,/oferta/\n",
    )
    host = blog.host

    assert _get(host, "/oferta/").status_code == 200
    assert _get(host, "/blog/").status_code == 200
    assert _verdict(host, "/oferta/") == {"rules": True, "gone": False}
    # A rule is a redirect only where its target answers today…
    missing = _get(host, "/stare")
    assert (missing.status_code, missing.data["code"]) == (404, "public_site_not_found")
    # …and never a way to another rule: one step or none.
    assert _moved(host, "/drugi") == (308, "/oferta/")
    assert _get(host, "/pierwszy").status_code == 404


def test_the_load_shows_first_and_is_safe_to_repeat(staff: str, tmp_path: Path) -> None:
    blog = Blog("old-map-load")
    rows = "/pl/oferta-stara,/oferta/\n/ogloszenia,gone\n/stare,/nie-ma/\n/blog,gone\n"

    shown = _load(blog, staff, tmp_path, rows, dry_run=True)
    assert _rules(blog) == {}
    assert "Reguły w pliku: 4 (308: 2, 410: 2)" in shown
    assert "Zmieniłoby się: 4 nowych" in shown
    # What a person should look at before the switch.
    assert "nowy adres dziś nie odpowiada" in shown and "/stare → /nie-ma/" in shown
    assert "stary adres odpowiada dziś na stronie" in shown and "/blog (→ /blog/)" in shown

    assert "Zapisano: 4 nowych, 0 zmienionych, 0 usuniętych; bez zmian 0." in _load(
        blog, staff, tmp_path, rows
    )
    assert "Zapisano: 0 nowych, 0 zmienionych, 0 usuniętych; bez zmian 4." in _load(
        blog, staff, tmp_path, rows
    )
    assert _rules(blog) == {
        "/pl/oferta-stara": "/oferta/",
        "/ogloszenia": "gone",
        "/stare": "/nie-ma/",
        "/blog": "gone",
    }

    # The file as the whole map: one rule changed, three gone from it.
    replaced = _load(blog, staff, tmp_path, "/ogloszenia,/oferta/\n", replace=True)
    assert "Zapisano: 0 nowych, 1 zmienionych, 3 usuniętych; bez zmian 0." in replaced
    assert _rules(blog) == {"/ogloszenia": "/oferta/"}
    loads = OrganizationAuditEntry.objects.filter(action=OLD_ADDRESSES_LOADED)
    assert [entry.metadata["added"] for entry in loads.order_by("occurred_at", "id")] == [4, 0, 0]


def test_a_refused_row_stops_the_whole_load(staff: str, tmp_path: Path) -> None:
    blog = Blog("old-map-refused")
    rows = (
        "/dobry,/oferta/\n"
        "bez-ukosnika,/oferta/\n"
        "/obcy,https://elsewhere.example.test/x\n"
        "/zapytanie,/oferta/?a=1\n"
        "/dwa-razy,/oferta/\n"
        "/DWA-razy/,gone\n"
        "/pusty,\n"
        # The same address in another spelling, and a row said twice: skipped.
        "/Oferta,/oferta/\n"
        "/dobry/,/oferta/\n"
    )
    out = StringIO()
    file = tmp_path / "old.csv"
    file.write_text(rows, encoding="utf-8")
    with pytest.raises(CommandError, match="Odrzucone wiersze: 5"):
        call_command(
            "load_old_addresses", host=blog.host, csv=str(file), operator=staff, stdout=out
        )
    assert _rules(blog) == {}
    assert "odrzucony wiersz 6: /DWA-razy/ — ten sam stary adres co w wierszu 5" in out.getvalue()

    plain = operator(email="nie-operator@example.test", staff=False)
    with pytest.raises(CommandError, match="uprawnień operatorskich"):
        call_command("load_old_addresses", host=blog.host, csv=str(file), operator=plain.email)
    with pytest.raises(CommandError, match="Żadna strona nie odpowiada"):
        call_command(
            "load_old_addresses", host="nobody.example.test", csv=str(file), operator=staff
        )


def test_a_link_to_a_section_follows_the_readers_language() -> None:
    """ADR-071 pkt 14, left open by PB1: `/blog/` written in a page leads an
    English reader to the section under its English name, as a link to a page
    leads to that page's English version."""
    blog = Blog("section-links")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    assert _rename(blog, "blog", {"en": "journal"}, reason="Angielska nazwa.").status_code == 200
    url = f"/api/v1/sites/{blog.site_id}/appearance/"
    current = blog.client.get(url).data
    appearance = current["appearance"]
    appearance["footer"]["links"] = [
        {"label": "Blog", "href": "/blog/#nowe"},
        {"label": "Oferta", "href": "/oferta/"},
    ]
    saved = blog.client.put(
        url,
        {"expected_version": current["version"], "appearance": appearance},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(blog.client),
        HTTP_IDEMPOTENCY_KEY="footer-links",
    )
    assert saved.status_code == 200, saved.data
    blog.publish("footer-links")

    def footer(path: str) -> list[str]:
        return [
            link["href"] for link in _get(blog.host, path).data["appearance"]["footer"]["links"]
        ]

    assert footer("/") == ["/blog/#nowe", "/oferta/"]
    # The section under its English name; the page without an English
    # version stays as written.
    assert footer("/en/") == ["/en/journal/#nowe", "/oferta/"]
    assert footer("/en/journal/in-english/") == ["/en/journal/#nowe", "/oferta/"]
