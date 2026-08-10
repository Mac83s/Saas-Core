from django.urls import path

from .views import HealthView, LivenessView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("health/live/", LivenessView.as_view(), name="health-live"),
]
