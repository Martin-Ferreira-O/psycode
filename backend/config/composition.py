from backend.apps.accounts.clients import EmailClient
from backend.apps.accounts.repositories import AccountsRepository
from backend.apps.accounts.services import AccountsService
from backend.apps.agenda.services import AgendaService
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService
from backend.apps.operational.capture_authorization import CaptureAuthorizationService


def accounts_service():
    return AccountsService(AccountsRepository(), EmailClient())


def alerts_repository():
    return AlertsRepository()


def alerts_service(store=None):
    from backend.apps.notifications.services import NotificationService
    repository = store if store is not None else AlertsRepository()
    return AlertsService(repository, NotificationService(store=repository))


def capture_authorization_service(agenda_service=None, config_loader=None):
    """SCRUM-70: Construye el servicio de autorización de captura por box para SCRUM-71."""
    return CaptureAuthorizationService(
        agenda_service=agenda_service if agenda_service is not None else AgendaService(),
        config_loader=config_loader,
    )


def analysis_worker(*, settings=None, directory=None, speechmatics_http=None, jev_http=None,
                    alert_store=None, audit=None):
    """Crear una vez dentro del trabajador interno. No iniciar en AppConfig/WSGI.

    Construirlo no abre red ni crea subprocesos. No llamarlo desde una vista HTTP.
    """
    from pathlib import Path
    from django.conf import settings as django_settings
    from backend.apps.analysis.audit import AnalysisAudit
    from backend.apps.analysis.clients import JevAnalizador, SpeechmaticsTranscriptor
    from backend.apps.analysis.ledger import FileFragmentLedger
    from backend.apps.analysis.providers.settings import Settings
    from backend.apps.analysis.services import AnalysisService

    config = settings or Settings.from_env()
    root = Path(directory) if directory is not None else django_settings.BASE_DIR / ".local/analysis"
    store = alert_store if alert_store is not None else AlertsRepository()

    def events():
        return store._events()

    return AnalysisService(
        SpeechmaticsTranscriptor(config, root / "jobs", speechmatics_http),
        JevAnalizador(config, jev_http), FileFragmentLedger(root / "fragments"),
        alerts_service(store), audit if audit is not None else AnalysisAudit(events),
        redact_terms=config.redact_terms,
        secrets=(config.speechmatics_key, config.jev_key, config.openrouter_key))
