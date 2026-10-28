from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView
from backend.common.responses import success_response
from .services import OperationalService


class IsActiveAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_active and getattr(user, "is_admin", False))


class OperationalConfigView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    service = OperationalService()

    def get(self, request):
        data = self.service.get_config()
        return success_response(data, "Configuración operativa recuperada")

    def put(self, request):
        data = self.service.update_config(actor=request.user, data=request.data)
        return success_response(data, "Configuración operativa actualizada")
