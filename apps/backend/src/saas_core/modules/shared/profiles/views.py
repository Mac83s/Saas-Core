from typing import Any, cast
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.content_protocol.units import unit_state
from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.locales import ContentLocaleField

from .catalog import catalog_entry_for, publish_profile, withdraw_profile
from .models import CatalogEntry, PublicProfile, PublicProfileTranslation
from .public_views import site_url
from .serializers import (
    OrganizationProfileSerializer,
    ProfileCreateSerializer,
    ProfileSummarySerializer,
    ProfileTranslationListSerializer,
    ProfileTranslationSerializer,
    ProfileTranslationSummarySerializer,
    ProfileUpdateSerializer,
)
from .services import (
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    list_translations,
    organization_profile,
    save_translation,
    update_profile,
)
from .translation_source import source_units, target_texts


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


def _translation(
    profile: PublicProfile, locale: str, translation: PublicProfileTranslation | None
) -> dict[str, Any]:
    units = source_units(profile)
    targets = target_texts(translation, units)
    rows = []
    for unit in units:
        target = targets.get(unit.key)
        rows.append({
            "key": unit.key,
            "source_text": unit.text,
            "text": target.text if target else "",
            "status": unit_state(unit, target).status,
            "origin": target.provenance.origin if target and target.provenance else "",
        })
    return {
        "locale": locale,
        "headline": translation.headline if translation else "",
        "bio": translation.bio if translation else "",
        "link_labels": dict(translation.link_labels or {}) if translation else {},
        "allow_headline_fallback": translation.allow_headline_fallback if translation else True,
        "allow_bio_fallback": translation.allow_bio_fallback if translation else True,
        "version": translation.version if translation else 0,
        "units": rows,
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


class ProfileTranslationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="profile_translations_list",
        summary="The card's translations, language by language",
        description="Every other language of the company with the card's text in it, unit by "
        "unit (headline, bio, link labels): the source text, the translation, its state against "
        "the current source (fresh, stale, missing…) and who wrote it, plus the version to send "
        "with a change.",
        tags=["profiles"],
        responses={200: ProfileTranslationListSerializer, 404: ProblemDetailsSerializer},
    )
    def get(self, _request: Request, profile_id: UUID) -> Response:
        profile, rows = list_translations(profile_id)
        return Response({
            "source_locale": profile.locale,
            "languages": [_translation(profile, code, row) for code, row in rows],
        })


@method_decorator(csrf_protect, name="dispatch")
class ProfileTranslationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="profile_translation_update",
        summary="Write the card in another language",
        description="A person's headline, bio and link labels in a language of the company, at "
        "the version they saw (0 for a new language; another answers 409). An absent field stays "
        "as it is. The change is in the history and the catalogue follows at once.",
        tags=["profiles"],
        request=ProfileTranslationSerializer,
        responses={
            200: ProfileTranslationSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "Locked by version: a repeat at the same version answers "
                "409 and changes nothing.",
            }
        },
    )
    def put(self, request: Request, profile_id: UUID, locale: str) -> Response:
        # The language in the address is checked like a field: shape, registry,
        # then the company's list in the service (ADR-071 pkt 3).
        try:
            ContentLocaleField().run_validation(locale)
        except ValidationError as error:
            raise ValidationError({"locale": error.detail}) from error
        serializer = ProfileTranslationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        translation = save_translation(
            profile_id, locale=locale, **cast(dict[str, Any], serializer.validated_data)
        )
        return Response(_translation(translation.profile, locale, translation))


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
