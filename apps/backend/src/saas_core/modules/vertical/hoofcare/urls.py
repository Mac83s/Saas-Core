from django.urls import path

from saas_core.modules.vertical.hoofcare.views import ModuleView

app_name = "hoofcare"

urlpatterns = [
    path("", ModuleView.as_view(), name="module"),
]
