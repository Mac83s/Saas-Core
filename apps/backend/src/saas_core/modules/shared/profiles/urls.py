from django.urls import path

from .views import (
    CatalogPublicationView,
    OrganizationProfileView,
    ProfileDetailView,
    ProfileListCreateView,
    ProfileTranslationView,
)

urlpatterns = [
    path("", ProfileListCreateView.as_view(), name="profile-list-create"),
    # Before the uuid route, so "organization" is never read as an identifier.
    path("organization/", OrganizationProfileView.as_view(), name="organization-profile"),
    path("organization/catalog/", CatalogPublicationView.as_view(), name="catalog-publication"),
    path("<uuid:profile_id>/", ProfileDetailView.as_view(), name="profile-detail"),
    path(
        "<uuid:profile_id>/translations/<slug:locale>/",
        ProfileTranslationView.as_view(),
        name="profile-translation",
    ),
]
