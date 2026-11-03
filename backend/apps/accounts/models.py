import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.db.models.functions import Lower


class Role(models.TextChoices):
    ADMIN = "admin", "Administrador"
    SUPERVISOR = "supervisor", "Supervisor"


class AccountsUserManager(UserManager):
    @classmethod
    def normalize_email(cls, email):
        return (email or "").strip().lower()


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SUPERVISOR,
        help_text="Rol del usuario en el sistema",
    )

    objects = AccountsUserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_email_case_insensitive"),
            models.CheckConstraint(condition=~models.Q(username__contains="@"), name="accounts_username_without_at"),
        ]

    @property
    def is_admin(self):
        return self.role == Role.ADMIN or self.is_superuser

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        if "@" in self.username:
            raise ValidationError({"username": "El nombre de usuario no puede contener @."})
        validate_email(self.email)

    def save(self, *args, **kwargs):
        self.username = self.normalize_username(self.username).strip()
        self.username_validator(self.username)
        self.clean()
        return super().save(*args, **kwargs)


class RefreshSession(models.Model):
    """Solo identificador firmado, nunca el JWT completo; rotación atómica."""
    jti = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_sessions")
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class PasswordReset(models.Model):
    """Un único token vigente por usuario, almacenado como digest SHA-256."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name="password_reset")
    token_hash = models.CharField(max_length=64, unique=True)
    credential_hash = models.CharField(max_length=32)
    expires_at = models.DateTimeField()


class PasswordResetRateLimit(models.Model):
    """Contadores por huella de IP y correo, compartidos entre procesos."""
    key = models.CharField(max_length=64, primary_key=True)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)