from django.urls import path

from .views import (
    CurrentOrganizationView,
    HistoryView,
    InvitationListCreateView,
    InvitationRevokeView,
    MembershipLeaveView,
    MembershipListView,
    MembershipUpdateView,
    OrganizationListCreateView,
    OwnershipTransferView,
    RoleDetailView,
    RoleListCreateView,
    SeatUsageView,
)

urlpatterns = [
    path("", OrganizationListCreateView.as_view(), name="organization-list-create"),
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
    path("current/seats/", SeatUsageView.as_view(), name="organization-seats"),
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
