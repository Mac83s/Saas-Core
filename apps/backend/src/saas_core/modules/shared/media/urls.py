from django.urls import path

from .views import MediaAssetListView, MediaUploadCompleteView, MediaUploadCreateView

app_name = "media"

urlpatterns = [
    path("", MediaAssetListView.as_view(), name="asset-list"),
    path("uploads/", MediaUploadCreateView.as_view(), name="upload-create"),
    path(
        "uploads/<uuid:asset_id>/complete/",
        MediaUploadCompleteView.as_view(),
        name="upload-complete",
    ),
]
