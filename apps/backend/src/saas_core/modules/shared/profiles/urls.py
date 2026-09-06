from django.urls import path

from .views import ProfileDetailView, ProfileListCreateView, ProfileTranslationView

urlpatterns = [
    path("", ProfileListCreateView.as_view(), name="profile-list-create"),
    path("<uuid:profile_id>/", ProfileDetailView.as_view(), name="profile-detail"),
    path(
        "<uuid:profile_id>/translations/<slug:locale>/",
        ProfileTranslationView.as_view(),
        name="profile-translation",
    ),
]
