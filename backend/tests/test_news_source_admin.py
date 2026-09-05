from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import admin_news_sources, create_news_source, delete_news_source, update_news_source
from app.models import NewsSource
from app.schemas import SourceCreate, SourceUpdate


class FakeSession:
    def __init__(self, row: NewsSource | None = None):
        self.row = row
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, _query):
        return self.row

    def get(self, _model, source_id):
        return self.row if self.row and self.row.id == source_id else None

    def add(self, row):
        row.id = row.id or 101
        self.row = row

    def commit(self):
        self.commits += 1

    def refresh(self, _row):
        return None

    def rollback(self):
        self.rollbacks += 1


def source_row(**overrides) -> NewsSource:
    values = {
        "id": 7,
        "name": "Example News",
        "coverage_area": "Indonesia",
        "domain": "example.com",
        "source_type": "RSS",
        "feed_url": "https://example.com/rss",
        "priority": 3,
        "credibility_score": 0.7,
        "fetch_frequency_minutes": 120,
        "is_active": True,
        "last_success_at": None,
        "last_error": None,
        "deleted_at": None,
    }
    values.update(overrides)
    return NewsSource(**values)


def test_source_schema_normalizes_and_validates_operator_input():
    payload = SourceCreate(
        name="  Example News  ",
        domain=" Example.COM. ",
        feed_url="https://example.com/rss",
    )
    assert payload.name == "Example News"
    assert payload.domain == "example.com"

    with pytest.raises(ValidationError):
        SourceCreate(
            name="Example News",
            domain="https://example.com/news",
            feed_url="https://example.com/rss",
        )


def test_create_source_returns_full_admin_contract():
    db = FakeSession()
    result = create_news_source(
        SourceCreate(name="Example News", coverage_area="Sumatera Utara", domain="example.com", feed_url="https://example.com/rss"),
        db,
    )

    assert result["id"] == 101
    assert result["domain"] == "example.com"
    assert result["coverage_area"] == "Sumatera Utara"
    assert result["fetch_frequency_minutes"] == 120
    assert result["active"] is True
    assert db.commits == 1


def test_create_source_rejects_an_existing_live_feed_url():
    db = FakeSession(source_row())
    with pytest.raises(HTTPException) as raised:
        create_news_source(
            SourceCreate(name="Duplicate", domain="example.com", feed_url="https://example.com/rss"),
            db,
        )
    assert raised.value.status_code == 409


def test_edit_delete_and_restore_source_preserves_identity():
    row = source_row()
    db = FakeSession(row)

    updated = update_news_source(
        row.id,
        SourceUpdate(name="Updated News", credibility_score=0.9, fetch_frequency_minutes=60),
        db,
    )
    assert updated["name"] == "Updated News"
    assert updated["credibility"] == 0.9
    assert updated["fetch_frequency_minutes"] == 60

    deleted = delete_news_source(row.id, db)
    assert deleted == {"id": 7, "deleted": True}
    assert row.is_active is False
    assert isinstance(row.deleted_at, datetime)
    assert row.deleted_at.tzinfo is not None

    restored = create_news_source(
        SourceCreate(
            name="Restored News",
            domain="example.com",
            feed_url="https://example.com/rss",
        ),
        db,
    )
    assert restored["id"] == 7
    assert restored["name"] == "Restored News"
    assert row.deleted_at is None
    assert row.is_active is True


def test_active_collectable_source_cannot_remove_feed_url():
    row = source_row()
    db = FakeSession(row)
    with pytest.raises(HTTPException) as raised:
        update_news_source(row.id, SourceUpdate(feed_url=None), db)
    assert raised.value.status_code == 422


def test_update_source_rejects_duplicate_feed_url():
    row = source_row()
    db = FakeSession(row)
    db.scalar = lambda _query: 99
    with pytest.raises(HTTPException) as raised:
        update_news_source(row.id, SourceUpdate(feed_url="https://other.example.com/rss"), db)
    assert raised.value.status_code == 409


def test_source_list_rejects_unknown_sort_column():
    with pytest.raises(HTTPException) as raised:
        admin_news_sources(
            FakeSession(),
            search=None,
            sort_by="not_a_column",
            sort_order="asc",
            page=1,
            per_page=25,
        )
    assert raised.value.status_code == 422
