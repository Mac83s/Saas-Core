from django.urls import path

from .domain_views import (
    SiteDomainActionView,
    SiteDomainListCreateView,
    SitePlatformDomainView,
)
from .onboarding_views import (
    SiteOnboardingCompleteView,
    SiteOnboardingView,
    SubdomainAvailabilityView,
)
from .views import (
    PageDraftPreviewView,
    PageDraftView,
    PageListCreateView,
    PageTranslationListView,
    PageTranslationView,
    SiteListCreateView,
    SiteLocalizationReportView,
    SiteNavigationView,
    SitePublicationCreateView,
    SitePublicationRollbackView,
)

app_name = "sites"

urlpatterns = [
    path(
        "subdomain-availability/",
        SubdomainAvailabilityView.as_view(),
        name="subdomain-availability",
    ),
    path("onboarding/", SiteOnboardingView.as_view(), name="onboarding"),
    path(
        "onboarding/complete/",
        SiteOnboardingCompleteView.as_view(),
        name="onboarding-complete",
    ),
    path(
        "<uuid:site_id>/domains/",
        SiteDomainListCreateView.as_view(),
        name="site-domain-list-create",
    ),
    path(
        "domains/<uuid:domain_id>/actions/",
        SiteDomainActionView.as_view(),
        name="site-domain-action",
    ),
    path(
        "<uuid:site_id>/platform-domain/",
        SitePlatformDomainView.as_view(),
        name="platform-domain-change",
    ),
    path("", SiteListCreateView.as_view(), name="list-create"),
    path("<uuid:site_id>/pages/", PageListCreateView.as_view(), name="page-list-create"),
    path(
        "<uuid:site_id>/localization/",
        SiteLocalizationReportView.as_view(),
        name="localization-report",
    ),
    path(
        "<uuid:site_id>/navigation/",
        SiteNavigationView.as_view(),
        name="navigation",
    ),
    path(
        "<uuid:site_id>/publications/",
        SitePublicationCreateView.as_view(),
        name="publication-create",
    ),
    path(
        "<uuid:site_id>/publications/<uuid:publication_id>/rollback/",
        SitePublicationRollbackView.as_view(),
        name="publication-rollback",
    ),
    path("pages/<uuid:page_id>/draft/", PageDraftView.as_view(), name="page-draft"),
    path(
        "pages/<uuid:page_id>/preview/<uuid:version_id>/",
        PageDraftPreviewView.as_view(),
        name="page-draft-preview",
    ),
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
