from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from backend.common.responses import success_response
from .serializers import OperationalConfigSerializer
from .services import OperationalService


class OperationalConfigView(APIView):
    permission_classes = [IsAuthenticated]
    service = OperationalService()

    def get(self, request):
        data = self.service.get_config()
        return success_response(data, "Configuración operativa recuperada")

    def put(self, request):
        serializer = OperationalConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = self.service.update_config(actor=request.user, data=serializer.validated_data)
        return success_response(data, "Configuración operativa actualizada")