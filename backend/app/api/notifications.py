from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from redis import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_internal_token
from app.config import settings
from app.database import get_db
from app.models import (
    EmailAccount,
    EmailOAuthProviderConfig,
    NotificationChannelConfig,
    NotificationDelivery,
    NotificationJob,
    NotificationOAuthState,
    NotificationRecipient,
    NotificationRecipientGroup,
    NotificationRecipientGroupMember,
    NotificationRule,
    NotificationRuleRecipient,
)
from app.notification.credentials import EmailCredentialError, email_credentials
from app.notification.enums import ConnectionStatus, EmailProviderType, NotificationChannel, NotificationJobStatus
from app.notification.oauth import EmailOAuthService, OAuthFlowError
from app.notification.oauth_config import (
    OAuthConfigurationError,
    normalize_email_provider,
    resolve_email_oauth_config,
)
from app.notification.renderer import EmailRenderer
from app.notification.service import NotificationService
from app.notification_schemas import (
    EmailNotificationSettingsUpdate,
    EmailOAuthProviderConfigUpdate,
    NotificationRuleCreate,
    NotificationRuleUpdate,
    RecipientCreate,
    RecipientGroupCreate,
    RecipientGroupUpdate,
    RecipientUpdate,
    TestEmailRequest,
)
from app.workers.celery_app import celery_app

router = APIRouter()
logger = logging.getLogger("fuel-intelligence.notification-api")
Db = Annotated[Session, Depends(get_db)]


def _channel_config(db: Session) -> NotificationChannelConfig:
    row = db.scalar(
        select(NotificationChannelConfig).where(NotificationChannelConfig.channel_type == NotificationChannel.EMAIL)
    )
    if not row:
        row = NotificationChannelConfig(channel_type=NotificationChannel.EMAIL, enabled=False)
        db.add(row)
        db.flush()
    return row


def _account_dict(row: EmailAccount) -> dict:
    return {
        "id": str(row.id),
        "account_name": row.account_name,
        "channel": row.channel,
        "provider": row.provider,
        "email_address": row.email_address,
        "display_name": row.display_name,
        "is_default": row.is_default,
        "enabled": row.enabled,
        "connection_status": row.connection_status,
        "oauth_scope": row.oauth_scope,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_failure_at": row.last_failure_at.isoformat() if row.last_failure_at else None,
        "last_error": row.last_error,
        "reconnect_required": row.connection_status in {ConnectionStatus.AUTH_ERROR, ConnectionStatus.TOKEN_EXPIRED},
    }


def _provider_name(provider: str) -> str:
    return "Google Gmail" if provider == EmailProviderType.GMAIL else "Microsoft Outlook / Exchange"


def _default_provider_redirect(provider: str) -> str:
    slug = "google" if provider == EmailProviderType.GMAIL else "microsoft"
    return f"{settings.app_base_url.rstrip('/')}/api/email/oauth/{slug}/callback"


def _provider_config_dict(db: Session, provider: str) -> dict:
    row = db.scalar(
        select(EmailOAuthProviderConfig).where(EmailOAuthProviderConfig.provider == provider)
    )
    try:
        resolved = resolve_email_oauth_config(provider, db)
        configuration_error = None
    except OAuthConfigurationError as exc:
        resolved = None
        configuration_error = str(exc)
    connected_accounts = db.scalar(
        select(func.count(EmailAccount.id)).where(
            EmailAccount.provider == provider,
            EmailAccount.enabled.is_(True),
            EmailAccount.connection_status == ConnectionStatus.CONNECTED,
        )
    ) or 0
    return {
        "provider": provider,
        "provider_name": _provider_name(provider),
        "configured": bool(resolved and resolved.configured),
        "client_id": resolved.client_id if resolved else row.client_id if row else None,
        "client_secret_configured": bool(resolved and resolved.client_secret),
        "tenant": (resolved.tenant if resolved else row.tenant if row else "common")
        if provider == EmailProviderType.MICROSOFT
        else None,
        "redirect_uri": (resolved.redirect_uri if resolved else row.redirect_uri if row else None)
        or _default_provider_redirect(provider),
        "credential_source": resolved.source if resolved else "database",
        "has_database_override": row is not None,
        "connected_accounts": connected_accounts,
        "configuration_error": configuration_error,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def _recipient_dict(row: NotificationRecipient) -> dict:
    return {
        "id": str(row.id), "name": row.name, "email_address": row.email_address, "enabled": row.enabled,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _group_dict(db: Session, row: NotificationRecipientGroup) -> dict:
    members = db.scalars(
        select(NotificationRecipient)
        .join(NotificationRecipientGroupMember, NotificationRecipientGroupMember.recipient_id == NotificationRecipient.id)
        .where(NotificationRecipientGroupMember.group_id == row.id)
        .order_by(NotificationRecipient.name)
    ).all()
    return {
        "id": str(row.id), "name": row.name, "description": row.description, "enabled": row.enabled,
        "members": [_recipient_dict(member) for member in members],
        "recipient_ids": [str(member.id) for member in members],
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _rule_targets(db: Session, rule_id: uuid.UUID) -> list[dict]:
    mappings = db.scalars(
        select(NotificationRuleRecipient).where(NotificationRuleRecipient.notification_rule_id == rule_id)
    ).all()
    result = []
    for mapping in mappings:
        recipient = db.get(NotificationRecipient, mapping.recipient_id) if mapping.recipient_id else None
        group = db.get(NotificationRecipientGroup, mapping.recipient_group_id) if mapping.recipient_group_id else None
        result.append(
            {
                "id": str(mapping.id),
                "recipient_id": str(mapping.recipient_id) if mapping.recipient_id else None,
                "recipient_group_id": str(mapping.recipient_group_id) if mapping.recipient_group_id else None,
                "recipient_role": mapping.recipient_role,
                "target_name": recipient.name if recipient else group.name if group else "Deleted target",
            }
        )
    return result


def _rule_dict(db: Session, row: NotificationRule) -> dict:
    account = db.get(EmailAccount, row.email_account_id) if row.email_account_id else None
    targets = _rule_targets(db, row.id)
    return {
        "id": str(row.id), "name": row.name, "description": row.description, "enabled": row.enabled,
        "channel": row.channel, "email_account_id": str(row.email_account_id) if row.email_account_id else None,
        "sender": account.account_name if account else "Default sender", "category": row.category,
        "minimum_severity": row.minimum_severity, "minimum_confidence_score": row.minimum_confidence_score,
        "province": row.province, "city_or_area": row.city_or_area,
        "tbbm_id": str(row.tbbm_id) if row.tbbm_id else None, "delivery_mode": row.delivery_mode,
        "digest_interval_minutes": row.digest_interval_minutes, "recipients": targets,
        "recipient_summary": ", ".join(f"{target['recipient_role']} {target['target_name']}" for target in targets) or "None",
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _replace_rule_targets(db: Session, rule: NotificationRule, payload: NotificationRuleCreate) -> None:
    db.execute(delete(NotificationRuleRecipient).where(NotificationRuleRecipient.notification_rule_id == rule.id))
    for target in payload.recipients:
        if target.recipient_id and not db.get(NotificationRecipient, target.recipient_id):
            raise HTTPException(422, "Recipient tidak ditemukan.")
        if target.recipient_group_id and not db.get(NotificationRecipientGroup, target.recipient_group_id):
            raise HTTPException(422, "Recipient group tidak ditemukan.")
        db.add(
            NotificationRuleRecipient(
                notification_rule_id=rule.id,
                recipient_id=target.recipient_id,
                recipient_group_id=target.recipient_group_id,
                recipient_role=target.recipient_role,
            )
        )


@router.get("/settings/notifications")
def get_notification_settings(db: Db) -> dict:
    channel = _channel_config(db)
    db.commit()
    return {"channels": [{"channel": channel.channel_type, "enabled": channel.enabled}]}


@router.get("/settings/notifications/email")
def get_email_notification_settings(db: Db) -> dict:
    channel = _channel_config(db)
    accounts = db.scalars(select(EmailAccount).order_by(EmailAccount.is_default.desc(), EmailAccount.account_name)).all()
    db.commit()
    return {"enabled": channel.enabled, "default_sender_id": next((str(row.id) for row in accounts if row.is_default), None)}


@router.put("/settings/notifications/email", dependencies=[Depends(require_internal_token)])
def update_email_notification_settings(
    payload: EmailNotificationSettingsUpdate, db: Db
) -> dict:
    channel = _channel_config(db)
    channel.enabled = payload.enabled
    db.commit()
    return {"enabled": channel.enabled}


@router.get("/email/provider-configs")
def list_email_provider_configs(db: Db) -> dict:
    providers = (str(EmailProviderType.GMAIL), str(EmailProviderType.MICROSOFT))
    return {"items": [_provider_config_dict(db, provider) for provider in providers]}


@router.put("/email/provider-configs/{provider}", dependencies=[Depends(require_internal_token)])
def save_email_provider_config(
    provider: str,
    payload: EmailOAuthProviderConfigUpdate,
    db: Db,
) -> dict:
    try:
        normalized = normalize_email_provider(provider)
    except OAuthConfigurationError as exc:
        raise HTTPException(404, str(exc)) from exc
    expected_callback = (
        "/api/email/oauth/google/callback"
        if normalized == EmailProviderType.GMAIL
        else "/api/email/oauth/microsoft/callback"
    )
    if not payload.redirect_uri.split("?", 1)[0].endswith(expected_callback):
        raise HTTPException(
            422,
            f"Redirect URI harus berakhir dengan {expected_callback}.",
        )
    tenant = (payload.tenant or "common").strip() if normalized == EmailProviderType.MICROSOFT else None
    row = db.scalar(
        select(EmailOAuthProviderConfig).where(EmailOAuthProviderConfig.provider == normalized)
    )
    environment = resolve_email_oauth_config(normalized)
    existing_secret_available = bool(row and row.client_secret_encrypted) or bool(environment.client_secret)
    if payload.client_secret is None and not existing_secret_available:
        raise HTTPException(422, "Client secret wajib diisi saat konfigurasi provider pertama kali disimpan.")

    secret_changed = payload.client_secret is not None
    identity_changed = bool(
        row
        and (
            row.client_id != payload.client_id
            or (normalized == EmailProviderType.MICROSOFT and (row.tenant or "common") != tenant)
        )
    )
    if not row:
        row = EmailOAuthProviderConfig(
            provider=normalized,
            client_id=payload.client_id,
            redirect_uri=payload.redirect_uri,
            tenant=tenant,
        )
        db.add(row)
    else:
        row.client_id = payload.client_id
        row.redirect_uri = payload.redirect_uri
        row.tenant = tenant
    if payload.client_secret is not None:
        try:
            row.client_secret_encrypted = email_credentials.encrypt(
                payload.client_secret.get_secret_value().strip()
            )
        except EmailCredentialError as exc:
            raise HTTPException(
                503,
                "Kunci enkripsi credential email belum siap di server.",
            ) from exc

    if identity_changed or secret_changed:
        db.execute(
            update(EmailAccount)
            .where(EmailAccount.provider == normalized, EmailAccount.enabled.is_(True))
            .values(
                connection_status=ConnectionStatus.AUTH_ERROR,
                last_error="Konfigurasi OAuth provider berubah. Hubungkan kembali akun.",
            )
        )
        db.execute(delete(NotificationOAuthState).where(NotificationOAuthState.provider == normalized))
    db.commit()
    db.refresh(row)
    logger.info(
        "email_oauth_provider_config_saved",
        extra={
            "provider": normalized,
            "secret_changed": secret_changed,
            "accounts_require_reconnect": identity_changed or secret_changed,
        },
    )
    return _provider_config_dict(db, normalized)


@router.delete("/email/provider-configs/{provider}", dependencies=[Depends(require_internal_token)])
def delete_email_provider_config(provider: str, db: Db) -> dict:
    try:
        normalized = normalize_email_provider(provider)
    except OAuthConfigurationError as exc:
        raise HTTPException(404, str(exc)) from exc
    row = db.scalar(
        select(EmailOAuthProviderConfig).where(EmailOAuthProviderConfig.provider == normalized)
    )
    removed = row is not None
    if row:
        db.delete(row)
        db.execute(
            update(EmailAccount)
            .where(EmailAccount.provider == normalized, EmailAccount.enabled.is_(True))
            .values(
                connection_status=ConnectionStatus.AUTH_ERROR,
                last_error="Konfigurasi OAuth provider dihapus. Hubungkan kembali akun.",
            )
        )
        db.execute(delete(NotificationOAuthState).where(NotificationOAuthState.provider == normalized))
        db.commit()
    logger.info(
        "email_oauth_provider_config_deleted",
        extra={"provider": normalized, "removed": removed},
    )
    result = _provider_config_dict(db, normalized)
    result["database_override_removed"] = removed
    return result


@router.get("/email/accounts")
def list_email_accounts(db: Db) -> dict:
    rows = db.scalars(select(EmailAccount).order_by(EmailAccount.is_default.desc(), EmailAccount.account_name)).all()
    return {"items": [_account_dict(row) for row in rows], "total": len(rows)}


@router.delete("/email/accounts/{account_id}", dependencies=[Depends(require_internal_token)])
def disconnect_email_account(account_id: uuid.UUID, db: Db) -> dict:
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(404, "Akun email tidak ditemukan.")
    account.enabled = False
    account.is_default = False
    account.connection_status = ConnectionStatus.DISCONNECTED
    account.oauth_access_token_encrypted = None
    account.oauth_refresh_token_encrypted = None
    account.oauth_token_expires_at = None
    account.last_error = None
    db.commit()
    logger.info("oauth_account_disconnected", extra={"account_id": str(account.id), "provider": account.provider})
    return {"id": str(account.id), "disconnected": True}


@router.post("/email/accounts/{account_id}/default", dependencies=[Depends(require_internal_token)])
def set_default_email_account(account_id: uuid.UUID, db: Db) -> dict:
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(404, "Akun email tidak ditemukan.")
    if not account.enabled or account.connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(409, "Hanya akun yang terhubung dapat menjadi default sender.")
    db.execute(update(EmailAccount).where(EmailAccount.id != account.id).values(is_default=False))
    account.is_default = True
    db.commit()
    return _account_dict(account)


def _enforce_test_rate_limit(account_id: uuid.UUID) -> None:
    key = f"notification:test-email:{account_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    try:
        redis = Redis.from_url(settings.redis_url, socket_timeout=2)
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, 70)
    except Exception as exc:
        raise HTTPException(503, "Rate-limit service tidak tersedia. Coba lagi.") from exc
    if count > settings.test_email_rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Batas test email tercapai. Coba lagi dalam satu menit.")


@router.post("/email/accounts/{account_id}/test", dependencies=[Depends(require_internal_token)], status_code=202)
def send_test_email(account_id: uuid.UUID, payload: TestEmailRequest, db: Db) -> dict:
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(404, "Akun email tidak ditemukan.")
    if not account.enabled or account.connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(409, "Hubungkan kembali akun email sebelum mengirim test.")
    _enforce_test_rate_limit(account_id)
    job = NotificationService(db).create_test_email_job(account, payload.recipient)
    db.commit()
    celery_app.send_task("fuel.notifications.dispatch", queue="notifications")
    return {"notification_job_id": str(job.id), "status": job.status}


@router.get("/email/oauth/{provider}/start", dependencies=[Depends(require_internal_token)])
def start_email_oauth(
    provider: str,
    db: Db,
    redirect_after_success: str = Query("/settings?tab=notifications-email"),
) -> dict:
    try:
        url = EmailOAuthService(db).authorization_url(provider, redirect_after_success)
    except OAuthFlowError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"authorization_url": url}


@router.get("/email/oauth/{provider}/callback")
def complete_email_oauth(
    provider: str,
    state: str,
    db: Db,
    code: str | None = None,
    error: str | None = None,
):
    service = EmailOAuthService(db)
    if error or not code:
        try:
            handshake = service.consume_state(provider, state)
            target = handshake.redirect_after_success
        except OAuthFlowError:
            target = "/settings?tab=notifications-email"
        return RedirectResponse(
            f"{settings.app_base_url.rstrip('/')}{target}{'&' if '?' in target else '?'}email_error={quote('Koneksi akun dibatalkan atau ditolak.')}",
            status_code=303,
        )
    try:
        account, target = service.complete(provider, code, state)
    except OAuthFlowError as exc:
        target = "/settings?tab=notifications-email"
        return RedirectResponse(
            f"{settings.app_base_url.rstrip('/')}{target}&email_error={quote(str(exc))}", status_code=303
        )
    logger.info("oauth_account_connected", extra={"account_id": str(account.id), "provider": account.provider})
    return RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}{target}{'&' if '?' in target else '?'}email_connected=1", status_code=303
    )


@router.get("/notification/recipients")
def list_recipients(db: Db) -> dict:
    rows = db.scalars(select(NotificationRecipient).order_by(NotificationRecipient.name)).all()
    return {"items": [_recipient_dict(row) for row in rows], "total": len(rows)}


@router.post("/notification/recipients", dependencies=[Depends(require_internal_token)], status_code=201)
def create_recipient(payload: RecipientCreate, db: Db) -> dict:
    row = NotificationRecipient(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Alamat email recipient sudah digunakan.") from exc
    return _recipient_dict(row)


@router.put("/notification/recipients/{recipient_id}", dependencies=[Depends(require_internal_token)])
def update_recipient(recipient_id: uuid.UUID, payload: RecipientUpdate, db: Db) -> dict:
    row = db.get(NotificationRecipient, recipient_id)
    if not row:
        raise HTTPException(404, "Recipient tidak ditemukan.")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Alamat email recipient sudah digunakan.") from exc
    return _recipient_dict(row)


@router.delete("/notification/recipients/{recipient_id}", dependencies=[Depends(require_internal_token)])
def delete_recipient(recipient_id: uuid.UUID, db: Db) -> dict:
    row = db.get(NotificationRecipient, recipient_id)
    if not row:
        raise HTTPException(404, "Recipient tidak ditemukan.")
    try:
        db.delete(row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Recipient masih digunakan oleh notification rule.") from exc
    return {"id": str(recipient_id), "deleted": True}


@router.get("/notification/recipient-groups")
def list_recipient_groups(db: Db) -> dict:
    rows = db.scalars(select(NotificationRecipientGroup).order_by(NotificationRecipientGroup.name)).all()
    return {"items": [_group_dict(db, row) for row in rows], "total": len(rows)}


def _save_group_members(db: Session, group: NotificationRecipientGroup, recipient_ids: list[uuid.UUID]) -> None:
    db.execute(delete(NotificationRecipientGroupMember).where(NotificationRecipientGroupMember.group_id == group.id))
    for recipient_id in dict.fromkeys(recipient_ids):
        if not db.get(NotificationRecipient, recipient_id):
            raise HTTPException(422, f"Recipient {recipient_id} tidak ditemukan.")
        db.add(NotificationRecipientGroupMember(group_id=group.id, recipient_id=recipient_id))


@router.post("/notification/recipient-groups", dependencies=[Depends(require_internal_token)], status_code=201)
def create_recipient_group(payload: RecipientGroupCreate, db: Db) -> dict:
    values = payload.model_dump(exclude={"recipient_ids"})
    row = NotificationRecipientGroup(**values)
    db.add(row)
    try:
        db.flush()
        _save_group_members(db, row, payload.recipient_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Nama recipient group sudah digunakan.") from exc
    return _group_dict(db, row)


@router.put("/notification/recipient-groups/{group_id}", dependencies=[Depends(require_internal_token)])
def update_recipient_group(
    group_id: uuid.UUID, payload: RecipientGroupUpdate, db: Db
) -> dict:
    row = db.get(NotificationRecipientGroup, group_id)
    if not row:
        raise HTTPException(404, "Recipient group tidak ditemukan.")
    for key, value in payload.model_dump(exclude={"recipient_ids"}).items():
        setattr(row, key, value)
    try:
        _save_group_members(db, row, payload.recipient_ids)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Nama recipient group sudah digunakan.") from exc
    return _group_dict(db, row)


@router.delete("/notification/recipient-groups/{group_id}", dependencies=[Depends(require_internal_token)])
def delete_recipient_group(group_id: uuid.UUID, db: Db) -> dict:
    row = db.get(NotificationRecipientGroup, group_id)
    if not row:
        raise HTTPException(404, "Recipient group tidak ditemukan.")
    try:
        db.delete(row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Recipient group masih digunakan oleh notification rule.") from exc
    return {"id": str(group_id), "deleted": True}


@router.get("/notification/rules")
def list_notification_rules(db: Db) -> dict:
    rows = db.scalars(select(NotificationRule).order_by(NotificationRule.name)).all()
    return {"items": [_rule_dict(db, row) for row in rows], "total": len(rows)}


@router.post("/notification/rules", dependencies=[Depends(require_internal_token)], status_code=201)
def create_notification_rule(payload: NotificationRuleCreate, db: Db) -> dict:
    if payload.channel != NotificationChannel.EMAIL:
        raise HTTPException(422, "Hanya channel EMAIL yang tersedia pada fase ini.")
    values = payload.model_dump(exclude={"recipients"})
    row = NotificationRule(**values)
    db.add(row)
    try:
        db.flush()
        _replace_rule_targets(db, row, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Nama notification rule sudah digunakan.") from exc
    return _rule_dict(db, row)


@router.put("/notification/rules/{rule_id}", dependencies=[Depends(require_internal_token)])
def update_notification_rule(
    rule_id: uuid.UUID, payload: NotificationRuleUpdate, db: Db
) -> dict:
    row = db.get(NotificationRule, rule_id)
    if not row:
        raise HTTPException(404, "Notification rule tidak ditemukan.")
    if payload.channel != NotificationChannel.EMAIL:
        raise HTTPException(422, "Hanya channel EMAIL yang tersedia pada fase ini.")
    for key, value in payload.model_dump(exclude={"recipients"}).items():
        setattr(row, key, value)
    try:
        _replace_rule_targets(db, row, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Nama notification rule sudah digunakan.") from exc
    return _rule_dict(db, row)


@router.delete("/notification/rules/{rule_id}", dependencies=[Depends(require_internal_token)])
def delete_notification_rule(rule_id: uuid.UUID, db: Db) -> dict:
    row = db.get(NotificationRule, rule_id)
    if not row:
        raise HTTPException(404, "Notification rule tidak ditemukan.")
    db.delete(row)
    db.commit()
    return {"id": str(rule_id), "deleted": True}


def _job_subject(job: NotificationJob) -> str:
    if not job.sender_account_id:
        return "Configuration error"
    try:
        return EmailRenderer().render(job.sender_account_id, job.payload_json).subject
    except (KeyError, ValueError):
        return "Notification"


def _job_dict(db: Session, row: NotificationJob) -> dict:
    account = db.get(EmailAccount, row.sender_account_id) if row.sender_account_id else None
    rule = db.get(NotificationRule, row.notification_rule_id) if row.notification_rule_id else None
    alert_payload = row.payload_json.get("alert", {})
    return {
        "id": str(row.id), "timestamp": row.created_at.isoformat(), "alert_id": row.alert_id,
        "incident_id": row.incident_id, "incident": alert_payload.get("incident_code"), "severity": alert_payload.get("severity"),
        "category": alert_payload.get("category"), "channel": row.channel, "provider": row.provider,
        "sender_account_id": str(row.sender_account_id) if row.sender_account_id else None,
        "sender": account.account_name if account else None, "recipient_summary": "; ".join(
            f"{role.upper()}: {', '.join(values)}" for role, values in row.payload_json.get("recipients", {}).items() if values
        ),
        "subject": _job_subject(row), "status": row.status, "attempts": row.attempt_count,
        "max_attempts": row.max_attempts, "rule": rule.name if rule else None,
        "created_at": row.created_at.isoformat(), "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "error_code": row.error_code, "error_message": row.last_error,
    }


@router.get("/notification/logs")
def list_notification_logs(
    db: Db,
    status_filter: str | None = Query(None, alias="status"),
    channel: str | None = None,
    provider: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    sender_account_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    query = select(NotificationJob)
    if status_filter:
        query = query.where(NotificationJob.status == status_filter.upper())
    if channel:
        query = query.where(NotificationJob.channel == channel.upper())
    if provider:
        query = query.where(NotificationJob.provider == provider.upper())
    if sender_account_id:
        query = query.where(NotificationJob.sender_account_id == sender_account_id)
    if date_from:
        query = query.where(NotificationJob.created_at >= date_from)
    if date_to:
        query = query.where(NotificationJob.created_at <= date_to)
    rows = db.scalars(query.order_by(NotificationJob.created_at.desc())).all()
    if severity:
        rows = [row for row in rows if row.payload_json.get("alert", {}).get("severity") == severity.upper()]
    if category:
        rows = [row for row in rows if row.payload_json.get("alert", {}).get("category") == category.upper()]
    total = len(rows)
    return {"items": [_job_dict(db, row) for row in rows[offset : offset + limit]], "total": total, "limit": limit, "offset": offset}


@router.get("/notification/logs/{job_id}")
def get_notification_log(job_id: uuid.UUID, db: Db) -> dict:
    row = db.get(NotificationJob, job_id)
    if not row:
        raise HTTPException(404, "Notification log tidak ditemukan.")
    deliveries = db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.notification_job_id == job_id)
        .order_by(NotificationDelivery.attempt_number)
    ).all()
    return {
        **_job_dict(db, row),
        "deliveries": [
            {
                "id": str(item.id), "status": item.status, "attempt_number": item.attempt_number,
                "started_at": item.started_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "provider_message_id": item.provider_message_id, "error_code": item.error_code,
                "error_message": item.error_message,
            }
            for item in deliveries
        ],
    }


@router.get("/notifications/health")
def notification_health(db: Db) -> dict:
    channel = _channel_config(db)
    accounts = db.scalars(select(EmailAccount)).all()
    now = datetime.now(timezone.utc)
    pending = db.scalar(select(func.count(NotificationJob.id)).where(NotificationJob.status == NotificationJobStatus.PENDING)) or 0
    retry = db.scalar(select(func.count(NotificationJob.id)).where(NotificationJob.status == NotificationJobStatus.RETRY)) or 0
    failed = db.scalar(
        select(func.count(NotificationJob.id)).where(
            NotificationJob.status == NotificationJobStatus.FAILED,
            NotificationJob.failed_at >= now - timedelta(hours=24),
        )
    ) or 0
    last_success = db.scalar(select(func.max(NotificationJob.sent_at)))
    connected = [row for row in accounts if row.enabled and row.connection_status == ConnectionStatus.CONNECTED]
    db.commit()
    return {
        "status": "HEALTHY" if failed == 0 else "DEGRADED",
        "email_channel": {"enabled": channel.enabled},
        "email_accounts": len(accounts),
        "connected_accounts": len(connected),
        "providers": {
            "GMAIL": sum(row.provider == EmailProviderType.GMAIL for row in connected),
            "MICROSOFT": sum(row.provider == EmailProviderType.MICROSOFT for row in connected),
        },
        "pending_jobs": pending, "retry_jobs": retry, "failed_last_24h": failed,
        "last_successful_send": last_success.isoformat() if last_success else None,
    }
