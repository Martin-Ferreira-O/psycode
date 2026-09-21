"""Cliente PyMongo perezoso. No abre sockets al importar el módulo ni al arrancar Django."""

from datetime import timezone
from pathlib import Path

from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.common.errors import PersistenceUnavailable

_CLIENT = None
_ESQUEMA_DIR = Path(__file__).resolve().parents[3] / "docs" / "mongodb"


def get_client():
    global _CLIENT
    uri = settings.MONGODB_URI
    if not uri:
        raise PersistenceUnavailable()
    if _CLIENT is None:
        # tz_aware: las fechas vuelven con tz UTC, como exige el dominio.
        _CLIENT = MongoClient(
            uri,
            tz_aware=True,
            tzinfo=timezone.utc,
            serverSelectionTimeoutMS=settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
            uuidRepresentation="standard",
        )
    return _CLIENT


def get_database():
    return get_client()[settings.MONGODB_DATABASE]


def ping():
    try:
        get_client().admin.command("ping")
    except PyMongoError:
        raise PersistenceUnavailable() from None


def close_client():
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.close()
        _CLIENT = None


def schema_path(nombre):
    return _ESQUEMA_DIR / nombre
