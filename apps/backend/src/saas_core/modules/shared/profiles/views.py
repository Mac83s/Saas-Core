from typing import Any, cast
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .catalog import catalog_entry_for, publish_profile, withdraw_profile
from .models import LOCALE_CHOICES, CatalogEntry, PublicProfile, PublicProfileTranslation
from .public_views import site_url
from .serializers import (
    OrganizationProfileSerializer,
    ProfileCreateSerializer,
    ProfileSummarySerializer,
    ProfileTranslationSerializer,
    ProfileTranslationSummarySerializer,
    ProfileUpdateSerializer,
)
from .services import (
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    organization_profile,
    save_translation,
    update_profile,
)


def _summary(profile: PublicProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "subject_kind": profile.subject_kind,
        "display_name": profile.display_name,
        "headline": profile.headline,
        "bio": profile.bio,
        "photo_id": profile.photo_id,
        "membership_id": profile.membership_id,
        "contact_email": profile.contact_email,
        "contact_phone": profile.contact_phone,
        "contact_address": profile.contact_address,
        "links": profile.links,
        "languages": profile.languages,
        "specializations": profile.specializations,
        "locale": profile.locale,
        "city_slug": profile.city_slug,
        "category": profile.category,
        "layout": profile.layout,
        "version": profile.version,
    }


def _translation(translation: PublicProfileTranslation) -> dict[str, Any]:
    return {
        "locale": translation.locale,
        "headline": translation.headline,
        "bio": translation.bio,
        "allow_headline_fallback": translation.allow_headline_fallback,
        "allow_bio_fallback": translation.allow_bio_fallback,
        "version": translation.version,
    }


@method_decorator(csrf_protect, name="dispatch")
class ProfileListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ProfileSummarySerializer(many=True)})
    def get(self, _request: Request) -> Response:
        return Response([_summary(profile) for profile in list_profiles()])

    @extend_schema(
        request=ProfileCreateSerializer,
        responses={
            201: ProfileSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = create_profile(**cast(dict[str, Any], serializer.validated_data))
        return Response(_summary(profile), status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class ProfileDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ProfileSummarySerializer, 404: ProblemDetailsSerializer})
    def get(self, _request: Request, profile_id: UUID) -> Response:
        return Response(_summary(get_profile(profile_id)))

    @extend_schema(
        request=ProfileUpdateSerializer,
        responses={
            200: ProfileSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, profile_id: UUID) -> Response:
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(dict[str, Any], serializer.validated_data)
        profile = update_profile(
            profile_id, expected_version=values.pop("expected_version"), **values
        )
        return Response(_summary(profile))

    @extend_schema(responses={204: None, 403: ProblemDetailsSerializer})
    def delete(self, _request: Request, profile_id: UUID) -> Response:
        delete_profile(profile_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class ProfileTranslationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ProfileTranslationSerializer,
        responses={
            200: ProfileTranslationSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, profile_id: UUID, locale: str) -> Response:
        if locale not in {code for code, _label in LOCALE_CHOICES}:
            return Response(
                {"detail": "Nieobsługiwane locale."}, status=status.HTTP_400_BAD_REQUEST
            )
        serializer = ProfileTranslationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        translation = save_translation(
            profile_id, locale=locale, **cast(dict[str, Any], serializer.validated_data)
        )
        return Response(_translation(translation))


def _catalog_state(entry: CatalogEntry | None) -> dict[str, Any]:
    if entry is None:
        return {
            "published": False,
            "city_slug": "",
            "slug": "",
            "path": "",
            "site_url": None,
            "published_at": None,
        }
    return {
        "published": True,
        "city_slug": entry.city_slug,
        "slug": entry.slug,
        "path": f"/katalog/{entry.city_slug}/{entry.slug}/",
        "site_url": site_url(entry),
        "published_at": entry.published_at,
    }


@method_decorator(csrf_protect, name="dispatch")
class OrganizationProfileView(APIView):
    """The company's own business card, plus whether it is in the catalogue.

    GET creates the profile when it does not exist yet (ADR-053 §2), which is
    why it is a separate endpoint from the generic list: the list must not have
    a side effect.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OrganizationProfileSerializer})
    def get(self, _request: Request) -> Response:
        profile = organization_profile()
        return Response({
            "profile": _summary(profile),
            "catalog": _catalog_state(catalog_entry_for(profile.organization_id)),
        })


@method_decorator(csrf_protect, name="dispatch")
class CatalogPublicationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: OrganizationProfileSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, _request: Request) -> Response:
        entry = publish_profile()
        return Response({"profile": _summary(entry.profile), "catalog": _catalog_state(entry)})

    @extend_schema(responses={204: None, 403: ProblemDetailsSerializer})
    def delete(self, _request: Request) -> Response:
        withdraw_profile()
        return Response(status=status.HTTP_204_NO_CONTENT)
