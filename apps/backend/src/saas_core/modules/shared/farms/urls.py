from django.urls import path

from .views import (
    AnimalDetailView,
    AnimalHealthPhotoView,
    AnimalHealthView,
    AnimalListCreateView,
    FarmActivationCodeView,
    FarmActivationRedeemView,
    FarmDetailView,
    FarmHerdPushView,
    FarmListCreateView,
    FarmShareListView,
    FarmShareRevokeView,
    FarmShareScheduleView,
    FarmVisitListView,
    SpeciesView,
)

urlpatterns = [
    path("", FarmListCreateView.as_view(), name="farms-list"),
    path("species/", SpeciesView.as_view(), name="farms-species"),
    path("animals/", AnimalListCreateView.as_view(), name="farms-animals"),
    path("animals/<uuid:animal_id>/", AnimalDetailView.as_view(), name="farms-animal-detail"),
    path(
        "animals/<uuid:animal_id>/health/",
        AnimalHealthView.as_view(),
        name="farms-animal-health",
    ),
    path(
        "health/<uuid:entry_id>/photos/<uuid:media_id>/",
        AnimalHealthPhotoView.as_view(),
        name="farms-health-photo",
    ),
    path("activation/redeem/", FarmActivationRedeemView.as_view(), name="farms-activation-redeem"),
    path(
        "shares/<uuid:share_id>/revoke/", FarmShareRevokeView.as_view(), name="farms-share-revoke"
    ),
    path(
        "shares/<uuid:share_id>/schedule/",
        FarmShareScheduleView.as_view(),
        name="farms-share-schedule",
    ),
    path("<uuid:farm_id>/", FarmDetailView.as_view(), name="farms-detail"),
    path(
        "<uuid:farm_id>/activation-code/",
        FarmActivationCodeView.as_view(),
        name="farms-activation-code",
    ),
    path("<uuid:farm_id>/shares/", FarmShareListView.as_view(), name="farms-shares"),
    path("<uuid:farm_id>/visits/", FarmVisitListView.as_view(), name="farms-visits"),
    path("<uuid:farm_id>/send-herd/", FarmHerdPushView.as_view(), name="farms-send-herd"),
]
