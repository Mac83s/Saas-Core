from django.urls import path

from saas_core.modules.vertical.medical.views import ModuleView

app_name = "medical"

urlpatterns = [
    path("", ModuleView.as_view(), name="module"),
]
