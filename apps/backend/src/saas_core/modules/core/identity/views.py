from typing import cast
from uuid import UUID

from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .mfa import begin_totp_enrollment, confirm_totp_enrollment
from .middleware import MANAGED_SESSION_KEY
from .models import User, UserSession
from .password_reset import (
    GENERIC_PASSWORD_RESET_MESSAGE,
    confirm_password_reset,
    request_password_reset,
)
from .serializers import (
    CsrfTokenSerializer,
    GenericMessageSerializer,
    LoginSerializer,
    MfaChallengeSerializer,
    MfaCodeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetResultSerializer,
    ProblemDetailsSerializer,
    RegistrationSerializer,
    SessionSummarySerializer,
    TotpConfirmResultSerializer,
    TotpSetupSerializer,
    UserSummarySerializer,
    VerificationConfirmSerializer,
    VerificationRequestSerializer,
    VerificationResultSerializer,
)
from .services import (
    GENERIC_VERIFICATION_MESSAGE,
    confirm_email_verification,
    register_user,
    request_email_verification,
)
from .sessions import (
    complete_mfa_enrollment_login,
    complete_mfa_login,
    login_user,
    logout_user,
    mfa_enrollment_user,
    revoke_user_session,
)


class PublicIdentityView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]


class OptionalIdentityView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]


class ProtectedIdentityView(APIView):
    permission_classes = [IsAuthenticated]


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfTokenView(PublicIdentityView):
    throttle_scope = "identity_verification_confirm"

    @extend_schema(responses={200: CsrfTokenSerializer, 429: ProblemDetailsSerializer})
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class RegistrationView(PublicIdentityView):
    throttle_scope = "identity_register"

    @extend_schema(
        request=RegistrationSerializer,
        responses={
            202: GenericMessageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        register_user(**serializer.validated_data)
        return Response(
            {"detail": GENERIC_VERIFICATION_MESSAGE},
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(csrf_protect, name="dispatch")
class LoginView(PublicIdentityView):
    throttle_scope = "identity_login"

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: UserSummarySerializer,
            202: MfaChallengeSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = login_user(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        if result.mfa_required:
            return Response(
                {"status": "mfa_required"},
                status=status.HTTP_202_ACCEPTED,
            )
        assert result.user is not None
        return Response(_user_summary(result.user))


@method_decorator(csrf_protect, name="dispatch")
class MfaLoginView(PublicIdentityView):
    throttle_scope = "identity_mfa_challenge"

    @extend_schema(
        request=MfaCodeSerializer,
        responses={
            200: UserSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = complete_mfa_login(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        return Response(_user_summary(user))


@method_decorator(csrf_protect, name="dispatch")
class TotpSetupView(OptionalIdentityView):
    throttle_scope = "identity_mfa_enrollment"

    @extend_schema(
        request=None,
        responses={
            200: TotpSetupSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        user, _ = mfa_enrollment_user(request=cast(HttpRequest, request))
        enrollment = begin_totp_enrollment(user=user)
        return Response({
            "secret": enrollment.secret,
            "provisioning_uri": enrollment.provisioning_uri,
        })


@method_decorator(csrf_protect, name="dispatch")
class TotpConfirmView(OptionalIdentityView):
    throttle_scope = "identity_mfa_enrollment"

    @extend_schema(
        request=MfaCodeSerializer,
        responses={
            200: TotpConfirmResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = MfaCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        http_request = cast(HttpRequest, request)
        user, preauthenticated = mfa_enrollment_user(request=http_request)
        recovery_codes = confirm_totp_enrollment(
            user=user,
            **serializer.validated_data,
            correlation_id=getattr(request, "correlation_id", None),
        )
        if preauthenticated:
            complete_mfa_enrollment_login(request=http_request, user=user)
        return Response({"status": "mfa_enabled", "recovery_codes": recovery_codes})


@method_decorator(csrf_protect, name="dispatch")
class VerificationRequestView(PublicIdentityView):
    throttle_scope = "identity_verification_resend"

    @extend_schema(
        request=VerificationRequestSerializer,
        responses={
            202: GenericMessageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = VerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_email_verification(**serializer.validated_data)
        return Response(
            {"detail": GENERIC_VERIFICATION_MESSAGE},
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(csrf_protect, name="dispatch")
class VerificationConfirmView(PublicIdentityView):
    throttle_scope = "identity_verification_confirm"

    @extend_schema(
        request=VerificationConfirmSerializer,
        responses={
            200: VerificationResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = VerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirm_email_verification(
            **serializer.validated_data,
            correlation_id=getattr(request, "correlation_id", None),
        )
        return Response({"status": "verified"})


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(PublicIdentityView):
    throttle_scope = "identity_password_reset_request"

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={
            202: GenericMessageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(**serializer.validated_data)
        return Response(
            {"detail": GENERIC_PASSWORD_RESET_MESSAGE},
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetConfirmView(PublicIdentityView):
    throttle_scope = "identity_password_reset_confirm"

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={
            200: PasswordResetResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirm_password_reset(
            **serializer.validated_data,
            correlation_id=getattr(request, "correlation_id", None),
        )
        return Response({"status": "password_updated"})


class CurrentUserView(ProtectedIdentityView):
    @extend_schema(responses={200: UserSummarySerializer, 403: ProblemDetailsSerializer})
    def get(self, request: Request) -> Response:
        return Response(_user_summary(cast(User, request.user)))


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(ProtectedIdentityView):
    @extend_schema(
        request=None,
        responses={204: None, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        logout_user(request=cast(HttpRequest, request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionListView(ProtectedIdentityView):
    @extend_schema(responses={200: SessionSummarySerializer(many=True)})
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        current_id = request.session.get(MANAGED_SESSION_KEY)
        sessions = UserSession.objects.filter(
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        return Response([
            {
                "id": tracking.id,
                "device_label": tracking.device_label,
                "created_at": tracking.created_at,
                "last_seen_at": tracking.last_seen_at,
                "expires_at": tracking.expires_at,
                "current": str(tracking.id) == current_id,
            }
            for tracking in sessions
        ])


@method_decorator(csrf_protect, name="dispatch")
class SessionRevokeView(ProtectedIdentityView):
    @extend_schema(
        responses={
            204: None,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        }
    )
    def delete(self, request: Request, session_id: UUID) -> Response:
        revoke_user_session(
            request=cast(HttpRequest, request),
            session_id=session_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _user_summary(user: User) -> dict[str, str]:
    return {
        "id": str(user.id),
        "email": user.email,
        "status": user.status,
        "locale": user.locale,
        "timezone": user.timezone,
    }
