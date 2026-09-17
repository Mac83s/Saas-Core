from django.urls import path

from saas_core.modules.vertical.hoofcare.views import (
    AnimalListCreateView,
    FarmListCreateView,
    HerdVisitListView,
    ModuleView,
)

app_name = "hoofcare"

urlpatterns = [
    path("", ModuleView.as_view(), name="module"),
    path("farms/", FarmListCreateView.as_view(), name="farm-list"),
    path("animals/", AnimalListCreateView.as_view(), name="animal-list"),
    path("visits/", HerdVisitListView.as_view(), name="visit-list"),
]
