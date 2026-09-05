"""add generic notification queue and email channel

Revision ID: 0011_email_notifications
Revises: 0010_tiktok_discovery
Create Date: 2026-09-05
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_email_notifications"
down_revision = "0010_tiktok_discovery"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_OBJECT = sa.text("'{}'::jsonb")
NOTIFICATION_TABLES = {
    "notification_channels",
    "email_accounts",
    "notification_recipients",
    "notification_recipient_groups",
    "notification_recipient_group_members",
    "notification_rules",
    "notification_rule_recipients",
    "notification_oauth_states",
    "notification_jobs",
    "notification_deliveries",
}


def _seed_defaults(bind) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO notification_channels (id, channel_type, enabled, created_at, updated_at) "
            "VALUES (:id, 'EMAIL', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (channel_type) DO NOTHING"
        ),
        {"id": uuid.uuid5(uuid.NAMESPACE_URL, "fuel-intelligence:notification-channel:email")},
    )
    defaults = (
        ("Critical incidents — immediate email", "CRITICAL", "IMMEDIATE", None),
        ("High incidents — immediate email", "HIGH", "IMMEDIATE", None),
        ("Medium incidents — hourly digest", "MEDIUM", "DIGEST", 60),
        ("Low incidents — dashboard only", "LOW", "DASHBOARD_ONLY", None),
    )
    for name, severity, mode, interval in defaults:
        bind.execute(
            sa.text(
                "INSERT INTO notification_rules "
                "(id, name, description, enabled, channel, minimum_severity, delivery_mode, digest_interval_minutes, created_at, updated_at) "
                "VALUES (:id, :name, 'Editable pilot policy template; assign sender and recipients before enabling.', false, 'EMAIL', :severity, :mode, :interval, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"fuel-intelligence:notification-rule:{name}"),
                "name": name,
                "severity": severity,
                "mode": mode,
                "interval": interval,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    notification_existing = NOTIFICATION_TABLES & existing
    if notification_existing:
        if notification_existing != NOTIFICATION_TABLES:
            missing = ", ".join(sorted(NOTIFICATION_TABLES - notification_existing))
            raise RuntimeError(f"Partial notification schema detected; missing tables: {missing}")
        _seed_defaults(bind)
        return
    op.create_table(
        "notification_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_type", sa.String(32), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_notification_channels_channel_type", "notification_channels", ["channel_type"])

    op.create_table(
        "email_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_name", sa.String(160), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="EMAIL"),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("email_address", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("oauth_access_token_encrypted", sa.Text()),
        sa.Column("oauth_refresh_token_encrypted", sa.Text()),
        sa.Column("oauth_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("oauth_scope", sa.Text(), nullable=False),
        sa.Column("oauth_provider_account_id", sa.String(255), nullable=False),
        sa.Column("connection_status", sa.String(32), nullable=False, server_default="CONNECTED"),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("provider", "oauth_provider_account_id", name="uq_email_account_provider_identity"),
    )
    op.create_index("ix_email_accounts_channel", "email_accounts", ["channel"])
    op.create_index("ix_email_accounts_provider", "email_accounts", ["provider"])
    op.create_index("ix_email_accounts_email_address", "email_accounts", ["email_address"])
    op.create_index("ix_email_accounts_connection_status", "email_accounts", ["connection_status"])
    op.create_index(
        "uq_email_accounts_active_default",
        "email_accounts",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default AND enabled"),
    )

    op.create_table(
        "notification_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email_address", sa.String(320), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_notification_recipients_email_address", "notification_recipients", ["email_address"])

    op.create_table(
        "notification_recipient_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "notification_recipient_group_members",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_recipient_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_recipients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("channel", sa.String(32), nullable=False, server_default="EMAIL"),
        sa.Column("email_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("email_accounts.id")),
        sa.Column("category", sa.String(64)),
        sa.Column("minimum_severity", sa.String(16)),
        sa.Column("minimum_confidence_score", sa.Float()),
        sa.Column("province", sa.String(120)),
        sa.Column("city_or_area", sa.String(160)),
        sa.Column("tbbm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_tbbm.id")),
        sa.Column("delivery_mode", sa.String(32), nullable=False, server_default="IMMEDIATE"),
        sa.Column("digest_interval_minutes", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    for name, columns in (
        ("ix_notification_rules_enabled", ["enabled"]),
        ("ix_notification_rules_channel", ["channel"]),
        ("ix_notification_rules_email_account_id", ["email_account_id"]),
        ("ix_notification_rules_category", ["category"]),
        ("ix_notification_rules_province", ["province"]),
        ("ix_notification_rules_tbbm_id", ["tbbm_id"]),
        ("ix_notification_rules_delivery_mode", ["delivery_mode"]),
    ):
        op.create_index(name, "notification_rules", columns)

    op.create_table(
        "notification_rule_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "notification_rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notification_recipients.id")),
        sa.Column(
            "recipient_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_recipient_groups.id"),
        ),
        sa.Column("recipient_role", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "(recipient_id IS NOT NULL) <> (recipient_group_id IS NOT NULL)",
            name="ck_notification_rule_recipient_exactly_one_target",
        ),
        sa.UniqueConstraint(
            "notification_rule_id", "recipient_id", "recipient_group_id", "recipient_role",
            name="uq_notification_rule_recipient_target_role",
        ),
    )
    op.create_index("ix_notification_rule_recipients_notification_rule_id", "notification_rule_recipients", ["notification_rule_id"])
    op.create_index("ix_notification_rule_recipients_recipient_id", "notification_rule_recipients", ["recipient_id"])
    op.create_index("ix_notification_rule_recipients_recipient_group_id", "notification_rule_recipients", ["recipient_group_id"])

    op.create_table(
        "notification_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("redirect_after_success", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notification_oauth_states_state_digest", "notification_oauth_states", ["state_digest"])
    op.create_index("ix_notification_oauth_states_provider", "notification_oauth_states", ["provider"])
    op.create_index("ix_notification_oauth_states_expires_at", "notification_oauth_states", ["expires_at"])

    op.create_table(
        "notification_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alert_history.id")),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id")),
        sa.Column(
            "notification_rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_rules.id", ondelete="SET NULL"),
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("sender_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("email_accounts.id")),
        sa.Column("delivery_mode", sa.String(32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_job_idempotency"),
    )
    for name, columns in (
        ("ix_notification_jobs_alert_id", ["alert_id"]),
        ("ix_notification_jobs_incident_id", ["incident_id"]),
        ("ix_notification_jobs_notification_rule_id", ["notification_rule_id"]),
        ("ix_notification_jobs_channel", ["channel"]),
        ("ix_notification_jobs_provider", ["provider"]),
        ("ix_notification_jobs_sender_account_id", ["sender_account_id"]),
        ("ix_notification_jobs_delivery_mode", ["delivery_mode"]),
        ("ix_notification_jobs_status", ["status"]),
        ("ix_notification_jobs_priority", ["priority"]),
        ("ix_notification_jobs_scheduled_at", ["scheduled_at"]),
        ("ix_notification_jobs_next_retry_at", ["next_retry_at"]),
        ("ix_notification_jobs_error_code", ["error_code"]),
    ):
        op.create_index(name, "notification_jobs", columns)

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("notification_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notification_jobs.id"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("sender_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("email_accounts.id")),
        sa.Column("recipient_summary", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_notification_deliveries_notification_job_id", "notification_deliveries", ["notification_job_id"])
    op.create_index("ix_notification_deliveries_channel", "notification_deliveries", ["channel"])
    op.create_index("ix_notification_deliveries_provider", "notification_deliveries", ["provider"])
    op.create_index("ix_notification_deliveries_sender_account_id", "notification_deliveries", ["sender_account_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])

    _seed_defaults(bind)


def downgrade() -> None:
    for table in (
        "notification_deliveries",
        "notification_jobs",
        "notification_oauth_states",
        "notification_rule_recipients",
        "notification_rules",
        "notification_recipient_group_members",
        "notification_recipient_groups",
        "notification_recipients",
        "email_accounts",
        "notification_channels",
    ):
        op.drop_table(table)
