from django.urls import path

from .views import (
    PageDraftView,
    PageListCreateView,
    PageTranslationListView,
    PageTranslationView,
    SiteListCreateView,
    SiteLocalizationReportView,
)

app_name = "sites"

urlpatterns = [
    path("", SiteListCreateView.as_view(), name="list-create"),
    path("<uuid:site_id>/pages/", PageListCreateView.as_view(), name="page-list-create"),
    path(
        "<uuid:site_id>/localization/",
        SiteLocalizationReportView.as_view(),
        name="localization-report",
    ),
    path("pages/<uuid:page_id>/draft/", PageDraftView.as_view(), name="page-draft"),
    path(
        "pages/<uuid:page_id>/translations/",
        PageTranslationListView.as_view(),
        name="page-translation-list",
    ),
    path(
        "pages/<uuid:page_id>/translations/<str:locale>/",
        PageTranslationView.as_view(),
        name="page-translation",
    ),
]
