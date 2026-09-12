from backend.apps.accounts.clients import EmailClient
from backend.apps.accounts.repositories import AccountsRepository
from backend.apps.accounts.services import AccountsService


def accounts_service():
    return AccountsService(AccountsRepository(), EmailClient())
