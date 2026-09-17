from typing import Any

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

MODULE_ID = "vertical.hoofcare"

ModuleSerializer = inline_serializer(
    name="HoofCareModule",
    fields={
        "module": serializers.CharField(),
        "version": serializers.IntegerField(),
    },
)


class ModuleView(APIView):
    """Answers only where the profile composed this module.

    The vertical layer had no module until HoofCare, so this endpoint exists to
    prove the composition reaches it: present in the `hoofcare` profile, absent
    everywhere else. Delete it once the module owns real endpoints — a route
    that only reports its own name is scaffolding, not a feature.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ModuleSerializer, operation_id="hoofcare_module")
    def get(self, request: Request) -> Response:
        payload: dict[str, Any] = {"module": MODULE_ID, "version": 1}
        return Response(payload)
