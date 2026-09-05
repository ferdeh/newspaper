from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailAccount, NotificationDelivery, NotificationJob
from app.notification.domain import NotificationDeliveryError
from app.notification.email_channel import EmailChannelAdapter
from app.notification.enums import ConnectionStatus, NotificationChannel, NotificationErrorCode, NotificationJobStatus
from app.notification.registries import NotificationChannelRegistry

logger = logging.getLogger("fuel-intelligence.notification-worker")


class NotificationWorker:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.channels = NotificationChannelRegistry()
        self.channels.register(NotificationChannel.EMAIL, lambda: EmailChannelAdapter(self.db))

    def recover_stale_jobs(self, stale_after_minutes: int = 10) -> int:
        result = self.db.execute(
            update(NotificationJob)
            .where(
                NotificationJob.status == NotificationJobStatus.PROCESSING,
                NotificationJob.processing_started_at < datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes),
            )
            .values(
                status=NotificationJobStatus.RETRY,
                next_retry_at=datetime.now(timezone.utc),
                error_code=NotificationErrorCode.PROVIDER_TEMPORARY_ERROR,
                last_error="Worker sebelumnya berhenti sebelum menyelesaikan pengiriman.",
            )
        )
        self.db.commit()
        return result.rowcount

    def claim_next_job(self) -> NotificationJob | None:
        now = datetime.now(timezone.utc)
        job = self.db.scalar(
            select(NotificationJob)
            .where(
                or_(
                    and_(NotificationJob.status == NotificationJobStatus.PENDING, NotificationJob.scheduled_at <= now),
                    and_(
                        NotificationJob.status == NotificationJobStatus.RETRY,
                        or_(NotificationJob.next_retry_at.is_(None), NotificationJob.next_retry_at <= now),
                    ),
                )
            )
            .order_by(NotificationJob.priority, NotificationJob.scheduled_at, NotificationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            self.db.rollback()
            return None
        job.status = NotificationJobStatus.PROCESSING
        job.processing_started_at = now
        job.attempt_count += 1
        self.db.commit()
        logger.info(
            "notification_job_claimed",
            extra={
                "notification_job_id": str(job.id),
                "alert_id": job.alert_id,
                "incident_id": job.incident_id,
                "channel": job.channel,
                "provider": job.provider,
                "attempt": job.attempt_count,
            },
        )
        return job

    def _digest_members(self, primary: NotificationJob) -> list[NotificationJob]:
        if primary.delivery_mode != "DIGEST" or not primary.notification_rule_id:
            return [primary]
        now = datetime.now(timezone.utc)
        siblings = self.db.scalars(
            select(NotificationJob)
            .where(
                NotificationJob.id != primary.id,
                NotificationJob.notification_rule_id == primary.notification_rule_id,
                NotificationJob.sender_account_id == primary.sender_account_id,
                NotificationJob.delivery_mode == "DIGEST",
                or_(
                    and_(NotificationJob.status == NotificationJobStatus.PENDING, NotificationJob.scheduled_at <= now),
                    and_(
                        NotificationJob.status == NotificationJobStatus.RETRY,
                        or_(NotificationJob.next_retry_at.is_(None), NotificationJob.next_retry_at <= now),
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in siblings:
            job.status = NotificationJobStatus.PROCESSING
            job.processing_started_at = now
            job.attempt_count += 1
        members = [primary, *siblings]
        alerts_by_id = {
            item.payload_json["alert"]["alert_id"]: item.payload_json["alert"]
            for item in members
            if item.payload_json.get("alert")
        }
        primary.payload_json = {**primary.payload_json, "alerts": list(alerts_by_id.values())}
        self.db.commit()
        return members

    def _delivery(self, job: NotificationJob) -> NotificationDelivery:
        recipients = job.payload_json.get("recipients", {})
        summary = "; ".join(
            f"{role.upper()}: {', '.join(values)}" for role, values in recipients.items() if values
        )
        delivery = NotificationDelivery(
            notification_job_id=job.id,
            channel=job.channel,
            provider=job.provider,
            sender_account_id=job.sender_account_id,
            recipient_summary=summary,
            status=NotificationJobStatus.PROCESSING,
            attempt_number=job.attempt_count,
        )
        self.db.add(delivery)
        self.db.flush()
        return delivery

    def process(self, primary: NotificationJob) -> bool:
        members = self._digest_members(primary)
        deliveries = [self._delivery(job) for job in members]
        self.db.commit()
        try:
            logger.info(
                "notification_channel_resolved",
                extra={"notification_job_id": str(primary.id), "channel": primary.channel},
            )
            channel = self.channels.get(primary.channel)
            logger.info(
                "notification_provider_resolved",
                extra={
                    "notification_job_id": str(primary.id),
                    "channel": primary.channel,
                    "provider": primary.provider,
                    "account_id": str(primary.sender_account_id) if primary.sender_account_id else None,
                },
            )
            logger.info(
                "email_send_started",
                extra={"notification_job_id": str(primary.id), "provider": primary.provider, "attempt": primary.attempt_count},
            )
            result = channel.send(primary)
        except NotificationDeliveryError as exc:
            self._fail(members, deliveries, exc)
            return False
        except (ValueError, KeyError) as exc:
            self._fail(
                members,
                deliveries,
                NotificationDeliveryError(NotificationErrorCode.CONFIGURATION_ERROR, str(exc)),
            )
            return False
        except Exception:
            logger.exception(
                "email_send_failed",
                extra={"notification_job_id": str(primary.id), "error_code": NotificationErrorCode.UNKNOWN_ERROR},
            )
            self._fail(
                members,
                deliveries,
                NotificationDeliveryError(
                    NotificationErrorCode.UNKNOWN_ERROR,
                    "Pengiriman email gagal karena kesalahan internal.",
                    retryable=True,
                ),
            )
            return False

        now = datetime.now(timezone.utc)
        for job, delivery in zip(members, deliveries, strict=True):
            job.status = NotificationJobStatus.SENT
            job.sent_at = now
            job.failed_at = None
            job.next_retry_at = None
            job.last_error = None
            job.error_code = None
            delivery.status = NotificationJobStatus.SENT
            delivery.provider_message_id = result.provider_message_id
            delivery.completed_at = now
        account = self.db.get(EmailAccount, primary.sender_account_id) if primary.sender_account_id else None
        if account:
            account.last_success_at = now
            account.last_error = None
            account.connection_status = ConnectionStatus.CONNECTED
        self.db.commit()
        logger.info(
            "email_send_success",
            extra={
                "notification_job_id": str(primary.id),
                "channel": primary.channel,
                "provider": primary.provider,
                "account_id": str(primary.sender_account_id) if primary.sender_account_id else None,
                "attempt": primary.attempt_count,
            },
        )
        return True

    def _fail(
        self,
        jobs: list[NotificationJob],
        deliveries: list[NotificationDelivery],
        error: NotificationDeliveryError,
    ) -> None:
        now = datetime.now(timezone.utc)
        for job, delivery in zip(jobs, deliveries, strict=True):
            can_retry = error.retryable and job.attempt_count < job.max_attempts
            job.status = NotificationJobStatus.RETRY if can_retry else NotificationJobStatus.FAILED
            job.error_code = error.code
            job.last_error = str(error)[:500]
            job.next_retry_at = now + timedelta(seconds=self._retry_delay(job.attempt_count)) if can_retry else None
            job.failed_at = None if can_retry else now
            delivery.status = job.status
            delivery.error_code = error.code
            delivery.error_message = str(error)[:500]
            delivery.completed_at = now
        account = self.db.get(EmailAccount, jobs[0].sender_account_id) if jobs[0].sender_account_id else None
        if account:
            account.last_failure_at = now
            account.last_error = str(error)[:500]
            if error.reconnect_required:
                account.connection_status = ConnectionStatus.AUTH_ERROR
        self.db.commit()
        event_name = "notification_retry_scheduled" if jobs[0].status == NotificationJobStatus.RETRY else "email_send_failed"
        logger.warning(
            event_name,
            extra={
                "notification_job_id": str(jobs[0].id),
                "channel": jobs[0].channel,
                "provider": jobs[0].provider,
                "account_id": str(jobs[0].sender_account_id) if jobs[0].sender_account_id else None,
                "attempt": jobs[0].attempt_count,
                "error_code": error.code,
                "status": jobs[0].status,
            },
        )

    @staticmethod
    def _retry_delay(attempt_count: int) -> int:
        delays = settings.notification_retry_delays_seconds or [0, 60, 300, 900]
        return delays[min(attempt_count, len(delays) - 1)]

    def run_batch(self, limit: int = 25) -> dict:
        self.recover_stale_jobs()
        processed = 0
        sent = 0
        while processed < limit:
            job = self.claim_next_job()
            if not job:
                break
            sent += int(self.process(job))
            processed += 1
        return {"processed": processed, "sent": sent, "failed_or_retry": processed - sent}
