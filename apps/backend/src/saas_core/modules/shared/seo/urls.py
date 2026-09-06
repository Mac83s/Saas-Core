from django.urls import include, path

from .views import AuditDetailView, AuditListView, AuditOfferView, SsaCallbackView

urlpatterns = [
    path("gsc/", include("saas_core.modules.shared.seo.gsc.urls")),
    path("audit-offer/", AuditOfferView.as_view(), name="seo-audit-offer"),
    path("audits/", AuditListView.as_view(), name="seo-audits"),
    path("audits/<uuid:order_id>/", AuditDetailView.as_view(), name="seo-audit-detail"),
    path("ssa/callback/", SsaCallbackView.as_view(), name="seo-ssa-callback"),
]
