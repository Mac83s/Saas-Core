from django.urls import path

from .views import (
    DocumentApprovePreviewView,
    DocumentApproveView,
    DocumentDetailView,
    DocumentDraftView,
    DocumentListView,
    DocumentTextView,
)

urlpatterns = [
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
