"""Public catalogue routes — no session, no tenant header (ADR-053 §4)."""

from django.urls import path

from .public_views import (
    PublicCatalogDetailView,
    PublicCatalogDictionaryView,
    PublicCatalogListView,
    PublicCatalogSitemapView,
)

urlpatterns = [
    path("", PublicCatalogListView.as_view(), name="public-catalog-list"),
    path("dictionary/", PublicCatalogDictionaryView.as_view(), name="public-catalog-dictionary"),
    path("sitemap/", PublicCatalogSitemapView.as_view(), name="public-catalog-sitemap"),
    path(
        "<slug:city_slug>/<slug:slug>/",
        PublicCatalogDetailView.as_view(),
        name="public-catalog-detail",
    ),
]
