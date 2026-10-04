from django.urls import path

from .views import (
    CustomerSearchView,
    DocumentApprovePreviewView,
    DocumentApproveView,
    DocumentDetailView,
    DocumentDraftView,
    DocumentListView,
    DocumentTextView,
    MarketingConsentListView,
    MarketingConsentWithdrawView,
)

urlpatterns = [
    path("search/", CustomerSearchView.as_view(), name="customers-search"),
    path(
        "consents/marketing/",
        MarketingConsentListView.as_view(),
        name="customers-marketing-consents",
    ),
    path(
        "consents/marketing/<uuid:customer_id>/withdraw/",
        MarketingConsentWithdrawView.as_view(),
        name="customers-marketing-consent-withdraw",
    ),
    path("documents/", DocumentListView.as_view(), name="customers-documents"),
    path("documents/<slug:kind>/", DocumentDetailView.as_view(), name="customers-document"),
    path(
        "documents/<slug:kind>/draft/",
        DocumentDraftView.as_view(),
        name="customers-document-draft",
    ),
    path(
        "documents/<slug:kind>/approve/preview/",
        DocumentApprovePreviewView.as_view(),
        name="customers-document-approve-preview",
    ),
    path(
        "documents/<slug:kind>/approve/",
        DocumentApproveView.as_view(),
        name="customers-document-approve",
    ),
    path(
        "documents/<slug:kind>/texts/",
        DocumentTextView.as_view(),
        name="customers-document-texts",
    ),
]
