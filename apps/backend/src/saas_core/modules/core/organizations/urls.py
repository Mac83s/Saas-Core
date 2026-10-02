from django.urls import path

from .public_locales_views import PublicLocalesPreviewView, PublicLocalesView
from .settings_views import settings_urlpatterns
from .views import (
    CommandConsentView,
    CurrentOrganizationView,
    HistoryView,
    InvitationListCreateView,
    InvitationRevokeView,
    MembershipLeaveView,
    MembershipListView,
    MembershipUpdateView,
    OrganizationListCreateView,
    OrganizationOptionsView,
    OwnershipTransferView,
    RoleDetailView,
    RoleListCreateView,
    SeatUsageView,
)

urlpatterns = [
    # Each settings group's read, preview and change (ADR-078 pkt 11).
    *settings_urlpatterns(),
    path("", OrganizationListCreateView.as_view(), name="organization-list-create"),
    path("options/", OrganizationOptionsView.as_view(), name="organization-options"),
    path("current/", CurrentOrganizationView.as_view(), name="organization-current"),
    path(
        "current/invitations/",
        InvitationListCreateView.as_view(),
        name="organization-invitation-list-create",
    ),
    path(
        "current/invitations/<uuid:invitation_id>/",
        InvitationRevokeView.as_view(),
        name="organization-invitation-revoke",
    ),
    path("current/history/", HistoryView.as_view(), name="organization-history"),
    path(
        "current/command-consents/<str:digest>/",
        CommandConsentView.as_view(),
        name="organization-command-consent",
    ),
    path("current/seats/", SeatUsageView.as_view(), name="organization-seats"),
    path(
        "current/public-locales/",
        PublicLocalesView.as_view(),
        name="organization-public-locales",
    ),
    path(
        "current/public-locales/preview/",
        PublicLocalesPreviewView.as_view(),
        name="organization-public-locales-preview",
    ),
    path("current/roles/", RoleListCreateView.as_view(), name="organization-roles"),
    path(
        "current/roles/<slug:role_key>/",
        RoleDetailView.as_view(),
        name="organization-role-detail",
    ),
    path(
        "current/members/",
        MembershipListView.as_view(),
        name="organization-membership-list",
    ),
    path(
        "current/members/<uuid:membership_id>/",
        MembershipUpdateView.as_view(),
        name="organization-membership-update",
    ),
    path(
        "current/members/me/leave/",
        MembershipLeaveView.as_view(),
        name="organization-membership-leave",
    ),
    path(
        "current/ownership-transfer/",
        OwnershipTransferView.as_view(),
        name="organization-ownership-transfer",
    ),
]
