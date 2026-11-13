from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(
    operation_id="health",
    summary="Liveness and database check",
    description="Answers 200 with status ok when the API is up and the database answers. No sign-in needed.",
    auth=[],
    responses={200: inline_serializer("Health", fields={"status": serializers.CharField()})},
    tags=["health"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return Response({"status": "ok"})
