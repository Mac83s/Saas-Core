from django.urls import path

from .views import (
    CsrfTokenView,
    RegistrationView,
    VerificationConfirmView,
    VerificationRequestView,
)

urlpatterns = [
    path("csrf/", CsrfTokenView.as_view(), name="identity-csrf"),
    path("register/", RegistrationView.as_view(), name="identity-register"),
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
