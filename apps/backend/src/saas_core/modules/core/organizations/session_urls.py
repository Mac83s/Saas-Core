from django.urls import path

from .views import ActiveOrganizationView

urlpatterns = [
    path(
        "active-organization/",
        ActiveOrganizationView.as_view(),
        name="session-active-organization",
    ),
]
