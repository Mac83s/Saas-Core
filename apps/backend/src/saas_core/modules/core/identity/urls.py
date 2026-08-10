from django.urls import path

from .views import (
    CsrfTokenView,
    CurrentUserView,
    LoginView,
    LogoutView,
    MfaLoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegistrationView,
    SessionListView,
    SessionRevokeView,
    TotpConfirmView,
    TotpSetupView,
    VerificationConfirmView,
    VerificationRequestView,
)

urlpatterns = [
    path("csrf/", CsrfTokenView.as_view(), name="identity-csrf"),
    path("register/", RegistrationView.as_view(), name="identity-register"),
    path("login/", LoginView.as_view(), name="identity-login"),
    path("login/mfa/", MfaLoginView.as_view(), name="identity-mfa-login"),
    path("logout/", LogoutView.as_view(), name="identity-logout"),
    path("mfa/totp/setup/", TotpSetupView.as_view(), name="identity-mfa-totp-setup"),
    path(
        "mfa/totp/confirm/",
        TotpConfirmView.as_view(),
        name="identity-mfa-totp-confirm",
    ),
    path(
        "password-resets/",
        PasswordResetRequestView.as_view(),
        name="identity-password-reset-request",
    ),
    path(
        "password-resets/confirm/",
        PasswordResetConfirmView.as_view(),
        name="identity-password-reset-confirm",
    ),
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
