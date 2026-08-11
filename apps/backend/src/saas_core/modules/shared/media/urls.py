from django.urls import path

from .views import MediaAssetListView, MediaUploadCreateView

app_name = "media"

urlpatterns = [
    path("", MediaAssetListView.as_view(), name="asset-list"),
    path("uploads/", MediaUploadCreateView.as_view(), name="upload-create"),
]
