from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from app.config import settings
from app.notification.domain import EmailMessage

SEVERITY_COLORS = {"CRITICAL": "#b91c1c", "HIGH": "#ea580c", "MEDIUM": "#ca8a04", "LOW": "#2563eb"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_email_address(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 320 or not EMAIL_RE.fullmatch(normalized) or "\r" in value or "\n" in value:
        raise ValueError("Alamat email tidak valid.")
    return normalized


def safe_subject(value: str, max_length: int = 180) -> str:
    clean = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return clean if len(clean) <= max_length else clean[: max_length - 1].rstrip() + "…"


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} else None


def _format_wib(value: str | datetime | None) -> str:
    if not value:
        return "—"
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.astimezone(settings.timezone).strftime("%d %b %Y %H:%M WIB")


class EmailRenderer:
    def render(self, sender_account_id: UUID, payload: dict) -> EmailMessage:
        template = payload.get("template", "immediate_alert")
        recipients = payload.get("recipients", {})
        if template == "test_email":
            subject, text_body, content = self._test(payload)
        elif template == "digest_alert":
            subject, text_body, content = self._digest(payload)
        else:
            subject, text_body, content = self._immediate(payload)
        html_body = self._shell(subject, content)
        return EmailMessage(
            sender_account_id=sender_account_id,
            to=tuple(validate_email_address(item) for item in recipients.get("to", [])),
            cc=tuple(validate_email_address(item) for item in recipients.get("cc", [])),
            bcc=tuple(validate_email_address(item) for item in recipients.get("bcc", [])),
            subject=safe_subject(subject),
            html_body=html_body,
            text_body=text_body,
            metadata={"template": template, "alert_id": payload.get("alert", {}).get("alert_id")},
        )

    def _subject_for_alert(self, alert: dict) -> str:
        severity = str(alert.get("severity", "LOW")).upper()
        title = str(alert.get("title") or alert.get("category") or "News Intelligence Alert")
        location = str(alert.get("location") or "")
        terminal = alert.get("nearest_tbbm_name")
        distance = alert.get("distance_tbbm_km")
        suffix = f" — {location}" if location else ""
        if terminal and distance is not None:
            suffix += f" — {float(distance):.1f} km dari {terminal}"
        return safe_subject(f"[{severity}] {title}{suffix}")

    def _immediate(self, payload: dict) -> tuple[str, str, str]:
        alert = payload.get("alert", {})
        severity = str(alert.get("severity", "LOW")).upper()
        color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["LOW"])
        subject = self._subject_for_alert(alert)
        dashboard_url = _safe_url(f"{settings.app_base_url.rstrip('/')}/incidents/{alert.get('incident_id')}")
        source_url = _safe_url(alert.get("source_url"))
        rows = [
            ("Published", _format_wib(alert.get("published_at"))),
            ("Source", str(alert.get("source_name") or "Multiple public signals")),
            ("Category", str(alert.get("category") or "—").replace("_", " ").title()),
            ("Risk Score", f"{float(alert.get('risk_score') or 0):.0f} / 100"),
            ("Confidence", f"{float(alert.get('confidence_score') or 0) * 100:.0f}%"),
        ]
        detail_rows = "".join(
            f'<tr><td style="padding:7px 12px;color:#64748b;width:34%">{html.escape(label)}</td>'
            f'<td style="padding:7px 12px;font-weight:700;color:#0f172a">{html.escape(value)}</td></tr>'
            for label, value in rows
        )
        terminal = html.escape(str(alert.get("nearest_tbbm_name") or "Belum tersedia"))
        distance = alert.get("distance_tbbm_km")
        distance_text = f"{float(distance):.1f} km" if distance is not None else "Belum tersedia"
        buttons = ""
        if source_url:
            buttons += f'<a href="{html.escape(source_url, quote=True)}" style="display:inline-block;margin:4px;padding:11px 16px;background:#0b73bf;color:#fff;text-decoration:none;border-radius:6px;font-weight:700">Open article</a>'
        if dashboard_url:
            buttons += f'<a href="{html.escape(dashboard_url, quote=True)}" style="display:inline-block;margin:4px;padding:11px 16px;background:#0f172a;color:#fff;text-decoration:none;border-radius:6px;font-weight:700">Open in dashboard</a>'
        content = f"""
          <div style="border-left:6px solid {color};padding:14px 18px;background:#f8fafc">
            <div style="font-size:12px;letter-spacing:1.5px;font-weight:800;color:{color}">{html.escape(severity)} ALERT</div>
            <h1 style="font-size:24px;line-height:1.25;margin:8px 0;color:#0f172a">{html.escape(str(alert.get('title') or 'News Intelligence Alert'))}</h1>
            <div style="color:#475569">{html.escape(str(alert.get('location') or 'Lokasi belum terverifikasi'))}</div>
          </div>
          <table role="presentation" style="width:100%;border-collapse:collapse;margin-top:16px">{detail_rows}</table>
          <h2 style="font-size:15px;margin:24px 0 8px;color:#0f172a">LOCATION INTELLIGENCE</h2>
          <table role="presentation" style="width:100%;border-collapse:collapse;background:#f8fafc">
            <tr><td style="padding:9px 12px;color:#64748b">Nearest Fuel Terminal</td><td style="padding:9px 12px;font-weight:700">{terminal}</td></tr>
            <tr><td style="padding:9px 12px;color:#64748b">Distance</td><td style="padding:9px 12px;font-weight:700">{html.escape(distance_text)}</td></tr>
          </table>
          <h2 style="font-size:15px;margin:24px 0 8px;color:#0f172a">SUMMARY</h2>
          <p style="line-height:1.65;color:#334155">{html.escape(str(alert.get('summary') or 'No summary available.'))}</p>
          <p style="color:#64748b">Sources detected: <strong>{int(alert.get('source_count') or 1)}</strong></p>
          <div style="text-align:center;margin:24px 0">{buttons}</div>
          <div style="font-size:12px;color:#64748b">Alert ID: {html.escape(str(alert.get('incident_code') or alert.get('alert_id') or '—'))}</div>
        """
        text = (
            f"NEWS INTELLIGENCE\n{severity} ALERT\n\n{alert.get('title', '')}\n{alert.get('location', '')}\n\n"
            f"Published: {_format_wib(alert.get('published_at'))}\nCategory: {alert.get('category', '—')}\n"
            f"Risk Score: {float(alert.get('risk_score') or 0):.0f} / 100\nConfidence: {float(alert.get('confidence_score') or 0) * 100:.0f}%\n\n"
            f"SUMMARY\n{alert.get('summary', '')}\n\nDashboard: {dashboard_url or '—'}"
        )
        return subject, text, content

    def _digest(self, payload: dict) -> tuple[str, str, str]:
        alerts = payload.get("alerts") or ([payload["alert"]] if payload.get("alert") else [])
        severity = str(alerts[0].get("severity", "MEDIUM")).upper() if alerts else "MEDIUM"
        provinces = sorted({str(item.get("province")) for item in alerts if item.get("province")})
        area = provinces[0] if len(provinces) == 1 else "Indonesia"
        now_label = datetime.now(settings.timezone).strftime("%H:%M WIB")
        subject = safe_subject(f"[{severity} DIGEST] {len(alerts)} BBM Incidents — {area} — {now_label}")
        cards = "".join(
            f'<tr><td style="padding:14px;border-bottom:1px solid #e2e8f0"><strong>{html.escape(str(item.get("title") or item.get("category") or "Incident"))}</strong><br>'
            f'<span style="font-size:12px;color:#64748b">{html.escape(str(item.get("location") or "Unresolved"))} · Risk {float(item.get("risk_score") or 0):.0f} · {html.escape(str(item.get("incident_code") or ""))}</span></td></tr>'
            for item in alerts
        )
        content = f'<h1 style="font-size:24px;color:#0f172a">{html.escape(severity)} Intelligence Digest</h1><p style="color:#64748b">{len(alerts)} incident-level alerts. Empty digests are never sent.</p><table role="presentation" style="width:100%;border-collapse:collapse">{cards}</table>'
        text = "NEWS INTELLIGENCE DIGEST\n\n" + "\n".join(
            f"- {item.get('title') or item.get('category')} — {item.get('location')} — Risk {float(item.get('risk_score') or 0):.0f}"
            for item in alerts
        )
        return subject, text, content

    def _test(self, payload: dict) -> tuple[str, str, str]:
        account = payload.get("account", {})
        timestamp = _format_wib(payload.get("timestamp"))
        subject = "[TEST] News Intelligence Email Notification"
        text = (
            "Email notification connection is working.\n\n"
            f"Provider: {account.get('provider', '—')}\nSender: {account.get('email_address', '—')}\nTimestamp: {timestamp}\n\nNews Intelligence"
        )
        content = f"""
          <div style="padding:20px;background:#ecfdf5;border-left:6px solid #059669">
            <h1 style="font-size:22px;margin:0 0 8px;color:#065f46">Connection successful</h1>
            <p style="margin:0;color:#047857">Email notification connection is working.</p>
          </div>
          <table role="presentation" style="width:100%;border-collapse:collapse;margin-top:18px">
            <tr><td style="padding:8px;color:#64748b">Provider</td><td style="padding:8px;font-weight:700">{html.escape(str(account.get('provider', '—')))}</td></tr>
            <tr><td style="padding:8px;color:#64748b">Sender</td><td style="padding:8px;font-weight:700">{html.escape(str(account.get('email_address', '—')))}</td></tr>
            <tr><td style="padding:8px;color:#64748b">Timestamp</td><td style="padding:8px;font-weight:700">{html.escape(timestamp)}</td></tr>
          </table>
        """
        return subject, text, content

    def _shell(self, title: str, content: str) -> str:
        return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
          <table role="presentation" style="width:100%;border-collapse:collapse;background:#f1f5f9"><tr><td align="center" style="padding:20px">
            <table role="presentation" style="width:100%;max-width:680px;border-collapse:collapse;background:#fff">
              <tr><td style="padding:18px 24px;background:#0f172a;color:#fff;font-size:12px;font-weight:800;letter-spacing:1.5px">NEWS INTELLIGENCE</td></tr>
              <tr><td style="padding:24px">{content}</td></tr>
              <tr><td style="padding:16px 24px;background:#f8fafc;color:#94a3b8;font-size:11px">Operational intelligence notification · Asia/Jakarta (WIB)</td></tr>
            </table>
          </td></tr></table><span style="display:none">{html.escape(title)}</span></body></html>"""
