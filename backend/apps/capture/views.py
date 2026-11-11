from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.views import APIView

from backend.common.responses import success_response
from backend.config.composition import fragment_ingestion_service
from .authentication import BoxAgentAuthentication
from .serializers import FragmentSerializer, FragmentV2Serializer, AgentConfigurationSerializer
from .storage import FragmentError
from .uploads import FragmentMultiPartParser
from .models import AgentRegistration, AgentConfiguration, ConfigurationState

@method_decorator(transaction.non_atomic_requests, name="dispatch")
class FragmentUploadView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [FragmentMultiPartParser]
    serializer_class = FragmentSerializer

    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            try:
                serializer.is_valid(raise_exception=True)
            except exceptions.ValidationError:
                raise FragmentError("VALIDATION_ERROR", 400) from None
            data = serializer.validated_data
            if data["box"] != request.user.box:
                raise exceptions.PermissionDenied()
            result, created = fragment_ingestion_service().receive(
                box=request.user.box, session_id=data["session_id"], number=data["secuencia"],
                format=data["formato"], checksum=data["checksum"], captured_at=data["captured_at"],
                upload=data["archivo"],
                agent_id=request.user.agent_id,
                temporal={k: data[k] for k in ("session_start_sample", "session_end_sample", "new_audio_start_sample",
                    "sample_rate", "chunk_samples", "overlap_samples")} if self.serializer_class is FragmentV2Serializer else None,
            )
            return success_response({
                "job_id": str(result.job_id), "session_id": str(result.session_id), "box": result.box,
                "secuencia": result.sequence, "formato": result.format, "checksum": result.checksum,
                "size_bytes": result.size, "accepted_at": result.accepted_at.isoformat().replace("+00:00", "Z"),
                "estado": "aceptado",
            }, "Fragmento recibido", status=201 if created else 200)
        except exceptions.UnsupportedMediaType:
            raise FragmentError("UNSUPPORTED_MEDIA_TYPE", 415) from None
        finally:
            handler = getattr(request, "_fragment_upload_handler", None)
            if handler is not None:
                handler.close()

class FragmentV2UploadView(FragmentUploadView):
    serializer_class = FragmentV2Serializer

class AgentConfigurationView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentRegistration, pk=agent_id)
        config = agent.configurations.order_by("-version").first()
        if not config:
            return success_response({
                "version": 0,
                "desired_config": {},
                "effective_config": {},
                "state": ConfigurationState.APPLIED
            }, "El equipo no tiene configuraciones remotas aún.")

        serializer = AgentConfigurationSerializer(config)
        return success_response(serializer.data, "Configuración obtenida con éxito.")

    def put(self, request, agent_id):
        agent = get_object_or_404(AgentRegistration, pk=agent_id)
        serializer = AgentConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            last_config = agent.configurations.select_for_update().order_by("-version").first()
            new_version = (last_config.version + 1) if last_config else 1
            requested_by = request.user.id if hasattr(request.user, 'id') else None
            
            new_config = AgentConfiguration.objects.create(
                agent=agent,
                requested_by=requested_by,
                desired_config=serializer.validated_data["desired_config"],
                effective_config=last_config.effective_config if last_config else {},
                version=new_version,
                state=ConfigurationState.PENDING
            )
            
        return success_response(
            AgentConfigurationSerializer(new_config).data,
            "Nueva configuración solicitada.",
            status=status.HTTP_201_CREATED
        )
