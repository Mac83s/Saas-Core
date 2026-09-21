"""Public catalogue routes — no session, no tenant header (ADR-053 §4)."""

from django.urls import path

from .public_views import (
    PublicCatalogDetailView,
    PublicCatalogDictionaryView,
    PublicCatalogListView,
)

urlpatterns = [
    path("", PublicCatalogListView.as_view(), name="public-catalog-list"),
    path("dictionary/", PublicCatalogDictionaryView.as_view(), name="public-catalog-dictionary"),
    path(
        "<slug:city_slug>/<slug:slug>/",
        PublicCatalogDetailView.as_view(),
        name="public-catalog-detail",
    ),
]
