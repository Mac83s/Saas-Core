from django.urls import path

from .views import (
    GlossaryCreatePreviewView,
    GlossaryDetailView,
    GlossaryListView,
    GlossaryUpdatePreviewView,
    JobDetailView,
    JobListView,
    QuoteView,
    TranslationOfferView,
    TranslationSettingsPreviewView,
    TranslationSettingsView,
)

urlpatterns = [
    path("quotes/", QuoteView.as_view(), name="translation-quotes"),
    path("jobs/", JobListView.as_view(), name="translation-jobs"),
    path("jobs/<uuid:job_id>/", JobDetailView.as_view(), name="translation-job"),
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
