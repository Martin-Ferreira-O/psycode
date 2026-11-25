import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import exceptions, serializers
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from backend.common.responses import success_response
from .authentication import BoxAgentAuthentication
from .models import AgentConnectivityEvent, CaptureSession
from .services import CaptureSessionService
from .storage import FragmentError


KINDS = tuple(f"{channel}.{transition}" for channel in ("https", "wss", "storage")
              for transition in ("disconnected", "reconnected"))
CAUSES = ("", "UNKNOWN", "TIMEOUT", "CONNECTION_ERROR", "HTTP_ERROR", "DISK_LOW",
          "STORAGE_WARNING", "STORAGE_CRITICAL", "LOCAL_WRITE_FAILED", "RECOVERY_REQUIRED")
MAX_EVENT_BYTES = 65536


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise FragmentError("EVENT_BATCH_TOO_LARGE", 413)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise FragmentError("VALIDATION_ERROR", 400) from None


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or data.keys() - self.fields.keys():
            raise serializers.ValidationError("INVALID_FIELDS")
        return super().to_internal_value(data)


class EventSerializer(StrictSerializer):
    event_id = serializers.UUIDField()
    session_id = serializers.UUIDField(allow_null=True)
    kind = serializers.ChoiceField(choices=KINDS)
    occurred_at = serializers.CharField(max_length=40)
    outage_id = serializers.UUIDField()
    duration_ms = serializers.IntegerField(min_value=0, max_value=9223372036854775807, allow_null=True)
    cause = serializers.ChoiceField(choices=CAUSES)

    def validate_occurred_at(self, value):
        try:
            instant = parse_datetime(value)
        except ValueError:
            instant = None
        if instant is None or timezone.is_naive(instant) or instant > timezone.now() + timedelta(seconds=30):
            raise serializers.ValidationError("INVALID_TIMESTAMP")
        return instant

    def validate(self, data):
        if data["kind"].endswith(".disconnected") and data["duration_ms"] is not None:
            raise serializers.ValidationError("INVALID_DURATION")
        return data


class EventBatchSerializer(StrictSerializer):
    version = serializers.ChoiceField(choices=("1.0",))
    events = EventSerializer(many=True, allow_empty=False, max_length=64)


class AgentEventsView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [BoundedJSONParser]

    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        if not serializer.is_valid():
            raise FragmentError("VALIDATION_ERROR", 400)
        ids = []
        with transaction.atomic():
            for event in serializer.validated_data["events"]:
                if event["session_id"] is not None and not CaptureSession.objects.filter(
                    pk=event["session_id"], box=request.user.box
                ).exists():
                    raise exceptions.PermissionDenied()
                defaults = {**event, "box": request.user.box}
                defaults.pop("event_id")
                stored, created = AgentConnectivityEvent.objects.get_or_create(
                    agent_id=request.user.agent_id, event_id=event["event_id"],
                    defaults={**defaults, "received_at": timezone.now()},
                )
                if not created and any(getattr(stored, key) != value for key, value in defaults.items()):
                    raise FragmentError("EVENT_CONFLICT", 409)
                ids.append(str(stored.event_id))
        return success_response({"version": "1.0", "accepted_event_ids": ids}, "Eventos recibidos")


class AgentSessionInspectionView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        return success_response(CaptureSessionService().inspection(request.user.box, session_id), "Estado de sesión")


class CaptureEndedSerializer(StrictSerializer):
    occurred_at = serializers.CharField(max_length=40)
    last_sequence = serializers.IntegerField(min_value=-1, max_value=9223372036854775806,
                                             allow_null=True, default=None)
    reason_code = serializers.ChoiceField(choices=("AUTHORIZATION_ENDED", "AGENT_STOPPED",
        "AGENT_INTERRUPTED", "RECOVERY_STOPPED", "DISK_LOW", "SHUTDOWN"))

    def validate_occurred_at(self, value):
        try:
            instant = parse_datetime(value)
        except ValueError:
            instant = None
        if instant is None or timezone.is_naive(instant):
            raise serializers.ValidationError("INVALID_TIMESTAMP")
        return instant


class AgentCaptureEndedView(AgentSessionInspectionView):
    parser_classes = [BoundedJSONParser]

    def post(self, request, session_id):
        serializer = CaptureEndedSerializer(data=request.data)
        if not serializer.is_valid():
            raise FragmentError("VALIDATION_ERROR", 400)
        data = serializer.validated_data
        service = CaptureSessionService()
        service.confirm_capture_ended(request.user.box, session_id, ended_at=data["occurred_at"],
            last_sequence=data["last_sequence"], reason_code=data["reason_code"])
        return success_response(service.inspection(request.user.box, session_id), "Cierre de captura recibido")
