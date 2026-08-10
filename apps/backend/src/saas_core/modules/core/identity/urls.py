from django.urls import path

from .views import (
    CsrfTokenView,
    CurrentUserView,
    LoginView,
    LogoutView,
    RegistrationView,
    SessionListView,
    SessionRevokeView,
    VerificationConfirmView,
    VerificationRequestView,
)

urlpatterns = [
    path("csrf/", CsrfTokenView.as_view(), name="identity-csrf"),
    path("register/", RegistrationView.as_view(), name="identity-register"),
    path("login/", LoginView.as_view(), name="identity-login"),
    path("logout/", LogoutView.as_view(), name="identity-logout"),
    path("me/", CurrentUserView.as_view(), name="identity-me"),
    path("sessions/", SessionListView.as_view(), name="identity-session-list"),
    path(
        "sessions/<uuid:session_id>/",
        SessionRevokeView.as_view(),
        name="identity-session-revoke",
    ),
    path(
        "email-verifications/resend/",
        VerificationRequestView.as_view(),
        name="identity-verification-resend",
    ),
    path(
        "email-verifications/confirm/",
        VerificationConfirmView.as_view(),
        name="identity-verification-confirm",
    ),
]
