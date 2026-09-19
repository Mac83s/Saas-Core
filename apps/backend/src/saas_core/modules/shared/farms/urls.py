from django.urls import path

from .views import (
    AnimalDetailView,
    AnimalListCreateView,
    FarmDetailView,
    FarmListCreateView,
    SpeciesView,
)

urlpatterns = [
    path("", FarmListCreateView.as_view(), name="farms-list"),
    path("species/", SpeciesView.as_view(), name="farms-species"),
    path("animals/", AnimalListCreateView.as_view(), name="farms-animals"),
    path("animals/<uuid:animal_id>/", AnimalDetailView.as_view(), name="farms-animal-detail"),
    path("<uuid:farm_id>/", FarmDetailView.as_view(), name="farms-detail"),
]
