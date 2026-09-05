from datetime import datetime, timedelta, timezone

from app.services.alerts import should_send_alert


def test_alert_cooldown_suppresses_unchanged_critical_incident():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert should_send_alert(82, now - timedelta(minutes=10), 84, 180, now) == (False, False)


def test_alert_escalation_bypasses_cooldown():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert should_send_alert(60, now - timedelta(minutes=10), 72, 180, now) == (True, True)


def test_same_band_does_not_repeat_after_cooldown():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert should_send_alert(68, now - timedelta(hours=4), 74, 180, now) == (False, False)
