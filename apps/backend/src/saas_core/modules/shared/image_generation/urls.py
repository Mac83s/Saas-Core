from django.urls import path

from .views import (
    ImageGenerationJobDetailView,
    ImageGenerationJobListView,
    ImageGenerationOfferView,
)

urlpatterns = [
    path("offer/", ImageGenerationOfferView.as_view(), name="image-generation-offer"),
    path("jobs/", ImageGenerationJobListView.as_view(), name="image-generation-jobs"),
    path(
        "jobs/<uuid:job_id>/",
        ImageGenerationJobDetailView.as_view(),
        name="image-generation-job-detail",
    ),
]
