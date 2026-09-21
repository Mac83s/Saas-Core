"""Product dictionaries replace only their own type, including an explicit opt-out."""

from dataclasses import replace
from typing import Any

from django.conf import settings as django_settings
from rest_framework.test import APIClient

from saas_core.config.composition import organization_types_from
from saas_core.modules.shared.profiles.catalog_contract import categories


def test_product_categories_reach_the_public_dictionary_without_cross_type_fallback(
    settings: Any,
) -> None:
    raw = {
        "key": "specialist_company",
        "label": {"pl": "Firma", "en": "Company"},
        "modules": ["shared.profiles"],
        "selfSignup": True,
        "catalogCategories": [
            {"key": "specialists", "label": {"pl": "Specjaliści", "en": "Specialists"}}
        ],
    }
    (company,) = organization_types_from({"organizationTypes": [raw]}, ("shared.profiles",))
    settings.ORGANIZATION_TYPES = {
        company.key: company,
        "private_company": replace(company, key="private_company", catalog_categories=()),
    }
    settings.DEFAULT_ORGANIZATION_TYPE = company.key
    response = APIClient().get("/api/v1/public/catalog/dictionary/")
    assert response.status_code == 200
    assert response.data["categories"] == [
        {"key": "specialists", "labels": {"pl": "Specjaliści", "en": "Specialists"}}
    ]
    assert categories("private_company") == {}
    assert categories("unknown_company") == {}
    assert "uroda-i-zdrowie" not in categories(company.key)


def test_missing_override_preserves_business_dictionary_but_empty_disables_it(
    settings: Any,
) -> None:
    default = django_settings.ORGANIZATION_TYPES[django_settings.DEFAULT_ORGANIZATION_TYPE]
    settings.ORGANIZATION_TYPES = {
        "business": replace(default, key="business", catalog_categories=None)
    }
    assert categories("business")["uroda-i-zdrowie"].label["pl"] == "Uroda i zdrowie"
    settings.ORGANIZATION_TYPES = {
        "business": replace(default, key="business", catalog_categories=())
    }
    assert categories("business") == {}
