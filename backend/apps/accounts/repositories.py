from django.db import transaction
from django.utils import timezone

from .models import PasswordReset, PasswordResetRateLimit, RefreshSession, User


class AccountsRepository:
    atomic = staticmethod(transaction.atomic)

    def find_user(self, identifier):
        if "@" in identifier:
            return self.find_by_email(identifier)
        return User.objects.filter(username=identifier).first()

    def find_by_email(self, email):
        return User.objects.filter(email__iexact=email).first()

    def find_by_id(self, user_id):
        return User.objects.filter(pk=user_id).first()

    def create_refresh(self, user, jti, expires_at):
        return RefreshSession.objects.create(user=user, jti=jti, expires_at=expires_at)

    def find_refresh(self, jti):
        return RefreshSession.objects.filter(jti=jti).first()

    def revoke_refresh(self, session):
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])

    def replace_reset(self, user, digest, credential_hash, expires_at):
        PasswordReset.objects.update_or_create(user=user, defaults={
            "token_hash": digest, "credential_hash": credential_hash, "expires_at": expires_at,
        })

    def count_reset_attempt(self, key, now, window):
        counter, _ = PasswordResetRateLimit.objects.get_or_create(
            key=key, defaults={"window_started_at": now, "count": 0},
        )
        if counter.window_started_at + window <= now:
            counter.window_started_at = now
            counter.count = 0
        counter.count += 1
        counter.save(update_fields=["window_started_at", "count"])
        return counter.count

    def find_reset(self, digest):
        return PasswordReset.objects.select_related("user").filter(token_hash=digest).first()

    def discard_reset(self, digest):
        # No eliminar una solicitud posterior si falla el envío de una anterior.
        PasswordReset.objects.filter(token_hash=digest).delete()

    def change_password(self, user, password):
        user.set_password(password)
        user.save(update_fields=["password"])
        PasswordReset.objects.filter(user=user).delete()
        RefreshSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
