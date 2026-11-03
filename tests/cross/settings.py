"""Solo integración sintética, nunca usar en producción."""
from backend.config.test_settings import *
from backend.common.errors import exception_handler
import traceback

def traced_handler(exc, context):
    traceback.print_exception(exc)
    return exception_handler(exc, context)

REST_FRAMEWORK = {**REST_FRAMEWORK, 'EXCEPTION_HANDLER':'tests.cross.settings.traced_handler'}
