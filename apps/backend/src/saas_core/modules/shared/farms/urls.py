from django.urls import path

from .views import (
    AnimalDetailView,
    AnimalListCreateView,
    FarmActivationCodeView,
    FarmActivationRedeemView,
    FarmDetailView,
    FarmListCreateView,
    FarmShareListView,
    FarmShareRevokeView,
    SpeciesView,
)

urlpatterns = [
    path("", FarmListCreateView.as_view(), name="farms-list"),
    path("species/", SpeciesView.as_view(), name="farms-species"),
    path("animals/", AnimalListCreateView.as_view(), name="farms-animals"),
    path("animals/<uuid:animal_id>/", AnimalDetailView.as_view(), name="farms-animal-detail"),
    path("activation/redeem/", FarmActivationRedeemView.as_view(), name="farms-activation-redeem"),
    path(
        "shares/<uuid:share_id>/revoke/", FarmShareRevokeView.as_view(), name="farms-share-revoke"
    ),
    path("<uuid:farm_id>/", FarmDetailView.as_view(), name="farms-detail"),
    path(
        "<uuid:farm_id>/activation-code/",
        FarmActivationCodeView.as_view(),
        name="farms-activation-code",
    ),
    path("<uuid:farm_id>/shares/", FarmShareListView.as_view(), name="farms-shares"),
]
