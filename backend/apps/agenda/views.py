import json
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser
from rest_framework.views import APIView
from backend.apps.capture.authentication import BoxAgentAuthentication
from backend.apps.capture.storage import FragmentError
from backend.apps.capture.uploads import FragmentMultiPartParser
from backend.common.responses import success_response
from . import persistence


class SmileConfigurationView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from backend.apps.operational.smile_configuration import agent_profile
        response = success_response(agent_profile(request.user), "Configuración Smile")
        response["Cache-Control"] = "no-store"
        return response


class CollectionView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        data = request.data
        if (not isinstance(data, dict) or set(data) not in ({"source"}, {"source", "revision"})
                or not isinstance(data["source"], str)
                or ("revision" in data and (type(data["revision"]) is not int or data["revision"] < 0))):
            raise FragmentError("VALIDATION_ERROR", 400)
        return success_response(persistence.issue(request.user, data["source"], revision=data.get("revision")),
                                "Recolección asignada", status=201)

@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ReportView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [FragmentMultiPartParser]

    def post(self, request):
        try:
            data = request.data
            if set(data) != {"archivo", "metadata"} or any(len(data.getlist(k)) != 1 for k in data):
                raise FragmentError("VALIDATION_ERROR", 400)
            if not isinstance(data["archivo"], UploadedFile):
                raise FragmentError("VALIDATION_ERROR", 400)
            try:
                metadata = json.loads(data["metadata"])
                result, created = persistence.receive(request.user, metadata, data["archivo"])
            except (ValueError, TypeError, KeyError):
                raise FragmentError("VALIDATION_ERROR", 400) from None
            return success_response(result, "Reporte recibido", status=201 if created else 200)
        finally:
            handler = getattr(request, "_fragment_upload_handler", None)
            if handler is not None:
                handler.close()


class SmileCatalogView(CollectionView):
    from backend.apps.capture.agent_events import BoundedJSONParser
    parser_classes = [BoundedJSONParser]

    def post(self, request):
        from .catalogue import publish
        return success_response(publish(request.user, request.data), "Catálogo de salas sincronizado")
