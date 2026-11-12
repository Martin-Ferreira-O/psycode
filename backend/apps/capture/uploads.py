"""Carga multipart acotada y privada; nunca usar el nombre enviado por el agente."""
from django.core.files.uploadedfile import UploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.utils.http import parse_header_parameters
from rest_framework.parsers import MultiPartParser

from .storage import FragmentError


class FragmentUploadHandler(FileUploadHandler):
    def __init__(self, request, storage, max_bytes=None):
        super().__init__(request)
        self.storage = storage
        self.max_bytes = storage.max_bytes if max_bytes is None else max_bytes
        self.received = 0
        self.started = False

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length > self.max_bytes + 64 * 1024:
            raise FragmentError("FRAGMENT_TOO_LARGE", 413)

    def new_file(self, field_name, *args, **kwargs):
        if field_name != "archivo" or self.started:
            raise FragmentError("VALIDATION_ERROR", 400)
        self.started = True
        self.file = self.storage.incoming()

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > self.max_bytes:
            raise FragmentError("FRAGMENT_TOO_LARGE", 413)
        self.file.write(raw_data)

    def file_complete(self, file_size):
        self.file.seek(0)
        return UploadedFile(self.file, name="fragment.wav", content_type="audio/wav", size=file_size)

    def close(self):
        if hasattr(self, "file"):
            self.file.close()

    def upload_interrupted(self):
        self.close()


class FragmentMultiPartParser(MultiPartParser):
    def parse(self, stream, media_type=None, parser_context=None):
        from backend.config.composition import fragment_storage
        request = parser_context["request"]
        from .chunk_config import byte_limit
        from .models import CaptureSession
        storage = fragment_storage()
        limit = storage.max_bytes
        # Antes de parsear no se conoce session_id (el multipart no exige orden).
        # Acotar por sesiones negociadas DEL box autenticado, luego revalidar
        # contra la sesión exacta antes de almacenar/aceptar el WAV.
        from .serializers import FragmentV2Serializer
        view = parser_context.get("view")
        if getattr(view, "serializer_class", None) is FragmentV2Serializer:
            for session in CaptureSession.objects.filter(box=request.user.box, capture_chunk_negotiated=True):
                limit = max(limit, byte_limit(session, storage.max_bytes))
        handler = FragmentUploadHandler(request._request, storage, limit)
        request._request.upload_handlers = [handler]
        try:
            guarded = MultipartStream(stream, handler.max_bytes + 64 * 1024)
            result = super().parse(guarded, media_type, parser_context)
            boundary = parse_header_parameters(media_type)[1].get("boundary", "").encode("ascii")
            if not guarded.tail.rstrip(b"\r\n").endswith(b"--" + boundary + b"--"):
                raise FragmentError("VALIDATION_ERROR", 400)
            return result
        except RequestDataTooBig:
            raise FragmentError("FRAGMENT_TOO_LARGE", 413) from None
        except (TooManyFieldsSent, TooManyFilesSent):
            raise FragmentError("VALIDATION_ERROR", 400) from None
        except OSError:
            raise FragmentError("FRAGMENT_STORAGE_UNAVAILABLE", 503) from None
        finally:
            # La vista necesita el archivo completo; en error el parser lo cierra.
            # El finally de la vista cubre también errores previos a request.FILES.
            request._fragment_upload_handler = handler


class MultipartStream:
    """Acota el cuerpo leído y exige el cierre multipart completo, sin epílogo."""
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit
        self.received = 0
        self.tail = b""

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.received += len(chunk)
        if self.received > self.limit:
            raise FragmentError("FRAGMENT_TOO_LARGE", 413)
        self.tail = (self.tail + chunk)[-256:]
        return chunk
