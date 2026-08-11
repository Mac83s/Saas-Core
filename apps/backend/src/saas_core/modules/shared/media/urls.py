from django.urls import path

from .views import (
    MediaAssetDeleteView,
    MediaAssetListView,
    MediaUploadCompleteView,
    MediaUploadCreateView,
)

app_name = "media"

urlpatterns = [
    path("", MediaAssetListView.as_view(), name="asset-list"),
    path("<uuid:asset_id>/", MediaAssetDeleteView.as_view(), name="asset-delete"),
    path("uploads/", MediaUploadCreateView.as_view(), name="upload-create"),
    path(
        "uploads/<uuid:asset_id>/complete/",
        MediaUploadCompleteView.as_view(),
        name="upload-complete",
    ),
]
