from django.urls import path

from .views import (
    DemandListView,
    GlossaryCreatePreviewView,
    GlossaryDetailView,
    GlossaryListView,
    GlossaryUpdatePreviewView,
    JobCancelView,
    JobDetailView,
    JobListView,
    JobRevertView,
    QuoteView,
    ReviewAcceptView,
    ReviewDetailView,
    ReviewDiscardView,
    ReviewListView,
    TranslationOfferView,
    TranslationSettingsPreviewView,
    TranslationSettingsView,
)

urlpatterns = [
    path("quotes/", QuoteView.as_view(), name="translation-quotes"),
    path("jobs/", JobListView.as_view(), name="translation-jobs"),
    path("jobs/<uuid:job_id>/", JobDetailView.as_view(), name="translation-job"),
    path("jobs/<uuid:job_id>/revert/", JobRevertView.as_view(), name="translation-job-revert"),
    path("jobs/<uuid:job_id>/cancel/", JobCancelView.as_view(), name="translation-job-cancel"),
    path("demand/", DemandListView.as_view(), name="translation-demand"),
    path("review/", ReviewListView.as_view(), name="translation-review"),
    path("review/accept/", ReviewAcceptView.as_view(), name="translation-review-accept"),
    path("review/discard/", ReviewDiscardView.as_view(), name="translation-review-discard"),
    path("review/<uuid:review_id>/", ReviewDetailView.as_view(), name="translation-review-item"),
    path("offer/", TranslationOfferView.as_view(), name="translation-offer"),
    path("settings/", TranslationSettingsView.as_view(), name="translation-settings"),
    path(
        "settings/preview/",
        TranslationSettingsPreviewView.as_view(),
        name="translation-settings-preview",
    ),
    path("glossary/", GlossaryListView.as_view(), name="translation-glossary"),
    path(
        "glossary/preview/",
        GlossaryCreatePreviewView.as_view(),
        name="translation-glossary-create-preview",
    ),
    path(
        "glossary/<uuid:term_id>/", GlossaryDetailView.as_view(), name="translation-glossary-term"
    ),
    path(
        "glossary/<uuid:term_id>/preview/",
        GlossaryUpdatePreviewView.as_view(),
        name="translation-glossary-update-preview",
    ),
]
