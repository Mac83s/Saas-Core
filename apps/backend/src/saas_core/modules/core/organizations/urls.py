from django.urls import path

from .views import CurrentOrganizationView, OrganizationListCreateView

urlpatterns = [
    path("", OrganizationListCreateView.as_view(), name="organization-list-create"),
    path("current/", CurrentOrganizationView.as_view(), name="organization-current"),
]
