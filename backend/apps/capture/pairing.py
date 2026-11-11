"""Vinculación de un uso: un código humano breve nunca es la credencial de máquina."""
from datetime import timedelta
import re
import json
import hashlib
import base64
import hmac
from uuid import UUID
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework import serializers
from rest_framework.parsers import JSONParser

from backend.apps.accounts.rate_limits import consume_auth_attempt
from backend.common.boxes import is_box
from backend.common.errors import ServiceError
from backend.common.responses import success_response
from .models import AgentRegistration, PCPairingCode, PCRegistryAllocation
from .pc_registry import _generate_credential, _invalidate_connection

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def registration_lock():
    PCRegistryAllocation.objects.get_or_create(pk=1)
    PCRegistryAllocation.objects.select_for_update().get(pk=1)


@transaction.atomic
def discard_abandoned_enrollments():
    registration_lock()
    AgentRegistration.objects.filter(
        token_sha256="", revoked_at__isnull=False, legacy_agent_id__isnull=True,
    ).filter(
        Q(pairing__isnull=True) | Q(pairing__activated_at__isnull=True, pairing__expires_at__lte=timezone.now()),
    ).delete()


def check_available_box(box):
    if not is_box(box):
        raise ServiceError("INVALID_BOX", "Identificador de sala inválido.", 400)
    if AgentRegistration.objects.filter(box=box).exists() or any(
        entry['box'] == box for entry in settings.CAPTURE_AGENTS.values()
    ):
        raise ServiceError("BOX_ALREADY_REGISTERED", "Esta sala ya tiene un PC. Renueva su vinculación desde el registro existente.", 409)


def code_digest(code):
    # La sal/clave de aplicación impide recorrer el pequeño espacio de códigos con solo un volcado SQL.
    return salted_hmac("psycode.pc.pairing.v1", code, algorithm="sha256").hexdigest()


def _issue_code(agent):
    expiry = timezone.now() + timedelta(seconds=settings.PC_PAIRING_TTL_SECONDS)
    # También se evita reutilizar códigos consumidos: no pueden vincular a otro PC durante un reintento.
    for _ in range(20):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(5))
        digest = code_digest(code)
        if PCPairingCode.objects.filter(code_hash=digest).exists():
            continue
        try:
            with transaction.atomic():
                PCPairingCode.objects.update_or_create(agent=agent, defaults={
                    'code_hash': digest, 'expires_at': expiry, 'consumed_at': None,
                    'installation_id': None, 'pending_token_sha256': '', 'activated_at': None,
                })
            return code, expiry
        except IntegrityError:
            continue
    raise ServiceError("PAIRING_UNAVAILABLE", "No se pudo emitir el código. Reintenta.", 503)


def _confirmed_room(agent):
    from backend.apps.agenda.models import SmileRoom
    # El registro del PC no depende de la disponibilidad de Smile. Una sala
    # retirada explícitamente sí bloquea nuevas instalaciones.
    room = SmileRoom.objects.filter(box=agent.box).first()
    if room and not room.available:
        raise ServiceError("SMILE_ROOM_UNAVAILABLE", "La sala está deshabilitada. Solicita una revisión técnica.", 409)
    return room


@transaction.atomic
def create_pairable_agent(*, name, room_id=None, box=None):
    from backend.apps.agenda.models import SmileRoom
    from backend.common.boxes import registrable_boxes
    from .legacy_registry import sync_legacy_registry
    discard_abandoned_enrollments()
    sync_legacy_registry()
    if room_id:
        room = SmileRoom.objects.select_for_update().filter(pk=room_id).first()
        if room is None:
            raise ServiceError("SMILE_ROOM_UNAVAILABLE", "Selecciona un box configurado.", 409)
        box = room.box
    else:
        room = SmileRoom.objects.select_for_update().filter(box=box).first()
        if room is None and box not in registrable_boxes():
            raise ServiceError("INVALID_BOX", "Selecciona un box configurado.", 400)
    if room and not room.available:
        raise ServiceError("SMILE_ROOM_UNAVAILABLE", "La sala está deshabilitada. Solicita una revisión técnica.", 409)
    candidates = list(AgentRegistration.objects.select_for_update().filter(box=box))
    if len(candidates) > 1:
        raise ServiceError("SMILE_ROOM_CONFLICT", "Hay varios equipos registrados en este box. Solicita una revisión técnica.", 409)
    created = not candidates
    agent = candidates[0] if candidates else AgentRegistration(name=name, box=box, token_sha256="", revoked_at=timezone.now())
    if room and agent.smile_room_id and agent.smile_room_id != room.pk:
        raise ServiceError("SMILE_ROOM_CONFLICT", "El PC está asociado a otra sala.", 409)
    agent.name = name
    if room:
        agent.smile_room = room
    agent.save()
    code, expiry = _issue_code(agent)
    agent.enrollment_created = created
    return agent, code, expiry


@transaction.atomic
def issue_pairing_code(agent_id):
    registration_lock()
    agent = get_object_or_404(AgentRegistration.objects.select_for_update(), pk=agent_id)
    grant = getattr(agent, "pairing", None)
    if agent.is_provisional and (grant is None or grant.expires_at <= timezone.now()):
        raise ServiceError("PAIRING_EXPIRED", "La instalación venció. Crea un nuevo PC en el box.", 409)
    _confirmed_room(agent)
    return agent, *_issue_code(agent)


def consume_pairing_attempt(source_ip):
    # Se cuentan éxitos y fallos; cambiar de IP o de código no elude el presupuesto global.
    consume_auth_attempt("pc.pair.ip", source_ip or "unknown", limit=settings.PC_PAIRING_IP_LIMIT,
                         seconds=settings.PC_PAIRING_WINDOW_SECONDS)
    consume_auth_attempt("pc.pair.global", "all", limit=settings.PC_PAIRING_GLOBAL_LIMIT,
                         seconds=settings.PC_PAIRING_WINDOW_SECONDS)


def _activate(agent, token_hash):
    from backend.apps.agenda.models import SmileRoom
    _invalidate_connection(agent, "CREDENTIAL_RENEWED")
    agent.token_sha256, agent.revoked_at, agent.legacy_enabled = token_hash, None, False
    agent.save(update_fields=['token_sha256', 'revoked_at', 'legacy_enabled', 'control_owner', 'updated_at'])
    SmileRoom.objects.filter(box=agent.box, legacy_blocked_at__isnull=True).update(legacy_blocked_at=timezone.now())


@transaction.atomic
def redeem_pairing_code(code, expected_box=None, installation_id=None, secret=None):
    registration_lock()
    grant = PCPairingCode.objects.filter(code_hash=code_digest(code)).first()
    if grant and grant.expires_at > timezone.now():
        agent = AgentRegistration.objects.select_for_update().get(pk=grant.agent_id)
        if expected_box is None or expected_box == agent.box:
            try:
                _confirmed_room(agent)
            except ServiceError:
                raise ServiceError("PAIRING_INVALID", "Instalación no disponible.", 400) from None
            if installation_id is not None:
                material = f"{agent.pk}:{installation_id}:{grant.code_hash}:{secret}"
                generated = base64.urlsafe_b64encode(salted_hmac(
                    'psycode.pc.credential.v2', material, algorithm='sha256',
                ).digest()).decode('ascii').rstrip('=')
                token = f"{agent.pk}.{generated}"
                digest = hashlib.sha256(token.encode('ascii')).hexdigest()
                if grant.consumed_at is None:
                    grant.installation_id, grant.pending_token_sha256 = installation_id, digest
                    grant.consumed_at = timezone.now()
                    grant.save(update_fields=['installation_id', 'pending_token_sha256', 'consumed_at'])
                elif grant.installation_id != installation_id or not hmac.compare_digest(grant.pending_token_sha256, digest):
                    raise ServiceError("PAIRING_INVALID", "Instalación no disponible.", 400)
                return agent, token
            if grant.consumed_at is None:
                # Compatibilidad con agentes anteriores: canje y activación en una respuesta.
                token, digest = _generate_credential(agent.pk)
                _activate(agent, digest)
                grant.consumed_at, grant.activated_at = timezone.now(), timezone.now()
                grant.save(update_fields=['consumed_at', 'activated_at'])
                return agent, token
    raise ServiceError("PAIRING_INVALID", "Código inválido, vencido o utilizado.", 400)


@transaction.atomic
def confirm_pairing(token, installation_id):
    registration_lock()
    try:
        agent_id, secret = token.split('.')
        agent_id = UUID(agent_id)
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', secret):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ServiceError("PAIRING_INVALID", "Instalación no disponible.", 400) from None
    agent = AgentRegistration.objects.select_for_update().filter(pk=agent_id).first()
    grant = PCPairingCode.objects.filter(agent=agent, installation_id=installation_id).first() if agent else None
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    if not grant or not hmac.compare_digest(grant.pending_token_sha256, digest):
        raise ServiceError("PAIRING_INVALID", "Instalación no disponible.", 400)
    # Confirmación perdida: solo la misma credencial ya activada puede repetirla.
    if grant.activated_at and agent.is_active and hmac.compare_digest(agent.token_sha256, digest):
        return agent
    if grant.expires_at <= timezone.now() or grant.activated_at:
        raise ServiceError("PAIRING_INVALID", "La instalación venció. Solicita otro código.", 400)
    _confirmed_room(agent)
    _activate(agent, digest)
    grant.activated_at = timezone.now()
    grant.save(update_fields=['activated_at'])
    return agent


class NewPCSerializer(serializers.Serializer):
    room_id = serializers.UUIDField(required=False)
    box = serializers.CharField(required=False)
    name = serializers.CharField(max_length=100, allow_blank=False, trim_whitespace=True)

    def validate(self, attrs):
        if bool(attrs.get('room_id')) == bool(attrs.get('box')):
            raise serializers.ValidationError("Selecciona un box configurado.")
        return attrs


def pairing_response(agent, code, expiry, status=200):
    return success_response({'agent_id': str(agent.pk), 'name': agent.name, 'box': agent.box,
                             'initial_installation': agent.is_provisional,
                             'pairing_code': code, 'expires_at': expiry}, "Código temporal generado", status=status)


class PCEnrollmentView(APIView):
    def get_permissions(self):
        # Importación local: los endpoints administrativos existentes comparten el permiso.
        from backend.apps.operational.views import IsActiveAdmin
        return [IsAuthenticated(), IsActiveAdmin()]

    def post(self, request):
        serializer = NewPCSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agent, code, expiry = create_pairable_agent(**serializer.validated_data)
        return pairing_response(agent, code, expiry, status=201 if agent.enrollment_created else 200)


class PCReEnrollmentView(PCEnrollmentView):
    def post(self, request, agent_id):
        return pairing_response(*issue_pairing_code(agent_id))


class PCEnrollmentCancelView(PCEnrollmentView):
    @transaction.atomic
    def post(self, request, agent_id):
        registration_lock()
        agent = get_object_or_404(AgentRegistration.objects.select_for_update(), pk=agent_id)
        grant = getattr(agent, "pairing", None)
        if grant and grant.activated_at:
            raise ServiceError("PAIRING_ALREADY_ACTIVE", "La instalación ya fue confirmada. Actualiza el estado del equipo.", 409)
        if agent.is_provisional:
            agent.delete()
        elif grant:
            grant.delete()
        return success_response({'agent_id': str(agent_id)}, "Instalación pendiente cancelada")


class PairingJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read(257)
        try:
            if len(raw) > 256:
                raise ValueError()
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ServiceError("PAIRING_INVALID", "Solicitud de vinculación inválida.", 400) from None


class PCPairingExchangeView(APIView):
    parser_classes = [PairingJSONParser]
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # No permitir que una configuración de proxy incorrecta convierta el enrolamiento en HTTP.
        if not request.is_secure():
            raise ServiceError("PAIRING_HTTPS_REQUIRED", "La vinculación requiere HTTPS.", 400)
        consume_pairing_attempt(request.META.get('REMOTE_ADDR', ''))
        # Cuerpo pequeño, sin reflejar el código recibido en errores.
        data = request.data
        code = data.get('code') if isinstance(data, dict) else None
        if not isinstance(code, str) or len(code) != 5 or any(c not in ALPHABET for c in code):
            raise ServiceError("PAIRING_INVALID", "Código inválido, vencido o utilizado.", 400)
        expected_box = data.get("expected_box")
        if expected_box is not None and not is_box(expected_box):
            raise ServiceError("PAIRING_INVALID", "Solicitud de vinculación inválida.", 400)
        installation_id, secret = data.get('installation_id'), data.get('secret')
        if installation_id is not None or secret is not None:
            try:
                installation_id = UUID(installation_id)
                if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', secret):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ServiceError("PAIRING_INVALID", "Solicitud de instalación inválida.", 400) from None
        agent, token = redeem_pairing_code(code, expected_box=expected_box, installation_id=installation_id, secret=secret)
        result = {'agent_id': str(agent.pk), 'name': agent.name, 'box': agent.box}
        result['api_key'] = token
        if installation_id:
            result.update({'installation_id': str(installation_id), 'confirmation_required': True})
        return success_response(result, "Instalación preparada" if installation_id else "PC vinculado")


class PCPairingConfirmView(PCPairingExchangeView):
    def post(self, request):
        if not request.is_secure():
            raise ServiceError("PAIRING_HTTPS_REQUIRED", "La instalación requiere HTTPS.", 400)
        consume_auth_attempt('pc.confirm.ip', request.META.get('REMOTE_ADDR', '') or 'unknown',
                             limit=60, seconds=settings.PC_PAIRING_WINDOW_SECONDS)
        from rest_framework.authentication import get_authorization_header
        try:
            scheme, token = get_authorization_header(request).decode('ascii').split()
            if scheme != 'Agent':
                raise ValueError()
            installation_id = UUID(request.data['installation_id'])
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
            raise ServiceError("PAIRING_INVALID", "Instalación no disponible.", 400) from None
        agent = confirm_pairing(token, installation_id)
        return success_response({'agent_id': str(agent.pk), 'box': agent.box}, "Instalación confirmada")
