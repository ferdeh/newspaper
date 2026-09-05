from enum import StrEnum


class NotificationChannel(StrEnum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"
    SLACK = "SLACK"
    MICROSOFT_TEAMS = "MICROSOFT_TEAMS"


class EmailProviderType(StrEnum):
    GMAIL = "GMAIL"
    MICROSOFT = "MICROSOFT"


class ConnectionStatus(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTH_ERROR = "AUTH_ERROR"
    ERROR = "ERROR"


class DeliveryMode(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    DIGEST = "DIGEST"
    DASHBOARD_ONLY = "DASHBOARD_ONLY"


class NotificationJobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY = "RETRY"
    SENT = "SENT"
    FAILED = "FAILED"


class RecipientRole(StrEnum):
    TO = "TO"
    CC = "CC"
    BCC = "BCC"


class NotificationErrorCode(StrEnum):
    PROVIDER_TEMPORARY_ERROR = "PROVIDER_TEMPORARY_ERROR"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_REFRESH_FAILED = "AUTH_REFRESH_FAILED"
    EMAIL_ACCOUNT_RECONNECT_REQUIRED = "EMAIL_ACCOUNT_RECONNECT_REQUIRED"
    ACCOUNT_DISCONNECTED = "ACCOUNT_DISCONNECTED"
    INVALID_RECIPIENT = "INVALID_RECIPIENT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def normalize_severity(value: str) -> str:
    normalized = value.upper()
    if normalized in {"CRITICAL", "HIGH"}:
        return normalized
    if normalized in {"WARNING", "MEDIUM"}:
        return "MEDIUM"
    return "LOW"
