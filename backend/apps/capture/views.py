import uuid
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.apps.operational.views import IsActiveAdmin
from backend.common.audit import AuditWriter
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

    def post(self, request, test_id=None):
        try:
            if test_id is not None:
                from .audio_tests import load_test
                load_test(test_id, request.user)
            serializer = self.serializer_class(data=request.data)
            try:
                serializer.is_valid(raise_exception=True)
            except exceptions.ValidationError:
                raise FragmentError("VALIDATION_ERROR", 400) from None
            data = serializer.validated_data
            if data["box"] != request.user.box:
                raise exceptions.PermissionDenied()
            if test_id is not None and test_id != data["session_id"]:
                raise FragmentError("AUDIO_TEST_CONFLICT", 409)
            result, created = fragment_ingestion_service().receive(
                box=request.user.box,
                session_id=data["session_id"],
                number=data["secuencia"],
                format=data["formato"],
                checksum=data["checksum"],
                captured_at=data["captured_at"],
                upload=data["archivo"],
                agent_id=request.user.agent_id if test_id is None else "",
                test_agent=request.user if test_id is not None else None,
                temporal={
                    k: data[k]
                    for k in (
                        "session_start_sample",
                        "session_end_sample",
                        "new_audio_start_sample",
                        "sample_rate",
                        "chunk_samples",
                        "overlap_samples",
                    )
                }
                if self.serializer_class is FragmentV2Serializer
                else None,
            )
            return success_response(
                {
                    "job_id": str(result.job_id),
                    "session_id": str(result.session_id),
                    "box": result.box,
                    "secuencia": result.sequence,
                    "formato": result.format,
                    "checksum": result.checksum,
                    "size_bytes": result.size,
                    "accepted_at": result.accepted_at.isoformat().replace("+00:00", "Z"),
                    "estado": "aceptado",
                },
                "Fragmento recibido",
                status=201 if created else 200,
            )
        except exceptions.UnsupportedMediaType:
            raise FragmentError("UNSUPPORTED_MEDIA_TYPE", 415) from None
        finally:
            handler = getattr(request, "_fragment_upload_handler", None)
            if handler is not None:
                handler.close()


class FragmentV2UploadView(FragmentUploadView):
    serializer_class = FragmentV2Serializer


class AgentConfigurationView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request, agent_id):
        agent = get_object_or_404(AgentRegistration, pk=agent_id)
        config = agent.configurations.order_by("-version").first()
        if not config:
            return success_response(
                {
                    "version": 0,
                    "desired_config": {},
                    "effective_config": {},
                    "state": ConfigurationState.APPLIED,
                },
                "El equipo no tiene configuraciones remotas aún.",
            )

        serializer = AgentConfigurationSerializer(config)
        return success_response(serializer.data, "Configuración obtenida con éxito.")

    def put(self, request, agent_id):
        agent = get_object_or_404(AgentRegistration, pk=agent_id)
        if not isinstance(request.data, dict):
            raise exceptions.ValidationError({"non_field_errors": ["Formato de solicitud inválido."]})

        serializer = AgentConfigurationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        base_version = serializer.validated_data.get("base_version")
        if base_version is None:
            base_version = serializer.validated_data.get("expected_version")
        if base_version is None and "version" in request.data:
            try:
                base_version = int(request.data["version"])
            except (TypeError, ValueError):
                raise exceptions.ValidationError({"version": ["Versión base inválida."]})

        requested_by = getattr(request.user, "pk", None) or getattr(request.user, "id", None)

        with transaction.atomic():
            last_config = agent.configurations.select_for_update().order_by("-version").first()
            current_version = last_config.version if last_config else 0

            conflict = False
            if base_version is not None and base_version != current_version:
                conflict = True
            elif (
                base_version is None
                and last_config is not None
                and last_config.state in {ConfigurationState.PENDING, ConfigurationState.RECEIVED}
            ):
                conflict = True

            if conflict:
                AuditWriter.emit(
                    {
                        "event_id": str(uuid.uuid4()),
                        "timestamp": timezone.now().isoformat(),
                        "action": "capture.agent_config.conflict",
                        "outcome": "failure",
                        "actor_id": str(requested_by) if requested_by else None,
                        "agent_id": str(agent.pk),
                        "box": agent.box,
                        "version": current_version,
                        "error_code": "CONFIG_VERSION_CONFLICT",
                    }
                )
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "CONFIG_VERSION_CONFLICT",
                            "message": "Conflicto: La configuración fue modificada o tiene una versión pendiente. Recargue antes de volver a editar.",
                            "details": {
                                "current_version": current_version,
                                "base_version": base_version,
                            },
                        },
                        "timestamp": timezone.now().isoformat(),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            new_version = current_version + 1

            new_config = AgentConfiguration.objects.create(
                agent=agent,
                requested_by=requested_by,
                desired_config=serializer.validated_data["desired_config"],
                effective_config=last_config.effective_config if last_config else {},
                version=new_version,
                state=ConfigurationState.PENDING,
            )

            AuditWriter.emit(
                {
                    "event_id": str(uuid.uuid4()),
                    "timestamp": timezone.now().isoformat(),
                    "action": "capture.agent_config.requested",
                    "outcome": "success",
                    "actor_id": str(requested_by) if requested_by else None,
                    "agent_id": str(agent.pk),
                    "box": agent.box,
                    "config_id": str(new_config.pk),
                    "version": new_version,
                    "state": new_config.state,
                }
            )

        return success_response(
            AgentConfigurationSerializer(new_config).data,
            "Nueva configuración solicitada.",
            status=status.HTTP_201_CREATED,
        )