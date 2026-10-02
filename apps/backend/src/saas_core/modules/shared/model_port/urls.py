from django.urls import path

from .views import ModelPortStatusView, ModelPortUsageView

urlpatterns = [
    path("platform/status/", ModelPortStatusView.as_view(), name="model-port-status"),
    path("platform/usage/", ModelPortUsageView.as_view(), name="model-port-usage"),
]
