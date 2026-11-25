from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from backend.apps.capture.authentication import BoxAgentAuthentication, ensure_agent_identity_current
from backend.apps.operational.smile_configuration import agent_profile
from backend.common.errors import ServiceError
from backend.common.responses import success_response

CAPABILITY = "agenda.smile-credentials.v1"


class SmileCredentialsView(APIView):
    authentication_classes = [BoxAgentAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "options"]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        response["Vary"] = "Authorization"
        return response

    def get(self, request):
        if not request.is_secure():
            raise ServiceError("SMILE_HTTPS_REQUIRED", "La entrega requiere HTTPS.", 400)
        ensure_agent_identity_current(request.user)
        profile = agent_profile(request.user)
        data = None
        if profile is not None:
            user, password = settings.SMILE_USERNAME, settings.SMILE_PASSWORD
            if any(not isinstance(value, str) or not value.strip() or len(value) > 1024
                   or any(char in value for char in "\x00\r\n") for value in (user, password)):
                raise ServiceError("SMILE_CREDENTIALS_UNAVAILABLE", "Credenciales Smile no configuradas en el servidor.", 503)
            data = {"version": "1", "revision": profile["revision"], "source": profile["source"],
                    "url": profile["url"], "username": user, "password": password}
        return success_response(data, "Credenciales Smile")
