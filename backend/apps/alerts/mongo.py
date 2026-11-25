from datetime import timezone
from pathlib import Path
from threading import RLock

from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.common.errors import PersistenceUnavailable

_CLIENT = None
_CLIENT_LOCK = RLock()
_SCHEMA_DATABASES = set()
_ESQUEMA_DIR = Path(__file__).resolve().parents[3] / "docs" / "mongodb"


def get_client():
    global _CLIENT
    uri = settings.MONGODB_URI
    if not uri:
        raise PersistenceUnavailable()
    with _CLIENT_LOCK:
        if _CLIENT is None:
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


def ensure_alert_schema(apply_schema):
    with _CLIENT_LOCK:
        database = get_database()
        if database.name not in _SCHEMA_DATABASES:
            apply_schema(database)
            _SCHEMA_DATABASES.add(database.name)
        return database


def ping():
    try:
        get_client().admin.command("ping")
    except PyMongoError:
        raise PersistenceUnavailable() from None


def close_client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            _CLIENT.close()
            _CLIENT = None
        _SCHEMA_DATABASES.clear()


def schema_path(nombre):
    return _ESQUEMA_DIR / nombre
