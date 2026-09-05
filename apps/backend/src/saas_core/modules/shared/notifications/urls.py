from django.urls import path

from .views import (
    ApiKeyListCreateView,
    ApiKeyRevokeView,
    ApiKeyRotateView,
    AppNotificationInboxView,
    AppNotificationReadView,
    DataExportCreateView,
    DataExportDetailView,
    DataExportDownloadView,
    PreferencesView,
    ProviderStatusWebhookView,
    SupportHealthView,
    SupportMessageRetryView,
    SupportWebhookRetryView,
    TemplateCatalogView,
    TemplatePreviewView,
    WebhookListCreateView,
)

app_name = "notifications"

urlpatterns = [
    path("inbox/", AppNotificationInboxView.as_view(), name="inbox"),
    path("inbox/read/", AppNotificationReadView.as_view(), name="inbox-read"),
    path("preferences/", PreferencesView.as_view(), name="preferences"),
    path("templates/", TemplateCatalogView.as_view(), name="template-list"),
    path("templates/preview/", TemplatePreviewView.as_view(), name="template-preview"),
    path("integrations/api-keys/", ApiKeyListCreateView.as_view(), name="api-key-list"),
    path(
        "integrations/api-keys/<uuid:key_id>/rotate/",
        ApiKeyRotateView.as_view(),
        name="api-key-rotate",
    ),
    path(
        "integrations/api-keys/<uuid:key_id>/revoke/",
        ApiKeyRevokeView.as_view(),
        name="api-key-revoke",
    ),
    path("integrations/webhooks/", WebhookListCreateView.as_view(), name="webhook-list"),
    path("exports/", DataExportCreateView.as_view(), name="export-create"),
    path("exports/<uuid:export_id>/", DataExportDetailView.as_view(), name="export-detail"),
    path(
        "exports/<uuid:export_id>/download/",
        DataExportDownloadView.as_view(),
        name="export-download",
    ),
    path(
        "support/webhooks/<uuid:delivery_id>/retry/",
        SupportWebhookRetryView.as_view(),
        name="support-webhook-retry",
    ),
    path("support/health/", SupportHealthView.as_view(), name="support-health"),
    path(
        "support/messages/<uuid:message_id>/retry/",
        SupportMessageRetryView.as_view(),
        name="support-message-retry",
    ),
    path("provider/status/", ProviderStatusWebhookView.as_view(), name="provider-status"),
]
