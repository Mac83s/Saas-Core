from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import (
    CsrfTokenSerializer,
    GenericMessageSerializer,
    ProblemDetailsSerializer,
    RegistrationSerializer,
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


class PublicIdentityView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]


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
        confirm_email_verification(**serializer.validated_data)
        return Response({"status": "verified"})
