from backend.apps.accounts.clients import EmailClient
from backend.apps.accounts.repositories import AccountsRepository
from backend.apps.accounts.services import AccountsService
from backend.apps.alerts.repositories import AlertsRepository
from backend.apps.alerts.services import AlertsService


def accounts_service():
    return AccountsService(AccountsRepository(), EmailClient())


def alerts_repository():
    return AlertsRepository()


def alerts_service(store=None):
    return AlertsService(store or AlertsRepository())
