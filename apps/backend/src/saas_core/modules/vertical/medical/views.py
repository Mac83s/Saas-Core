from typing import Any

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

MODULE_ID = "vertical.medical"

ModuleSerializer = inline_serializer(
    name="MedicalModule",
    fields={
        "module": serializers.CharField(),
        "version": serializers.IntegerField(),
    },
)


class ModuleView(APIView):
    """Answers only where the profile composed this module.

    The same placeholder the HoofCare vertical carries, for the same reason:
    it proves the deployment runs this module and nothing more. Delete it once
    MedPlano owns real endpoints. The duplication is deliberate — one vertical
    may not import another, so there is no shared base view to inherit.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ModuleSerializer, operation_id="medical_module")
    def get(self, request: Request) -> Response:
        payload: dict[str, Any] = {"module": MODULE_ID, "version": 1}
        return Response(payload)
