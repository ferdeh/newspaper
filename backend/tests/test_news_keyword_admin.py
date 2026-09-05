from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import create_news_keyword, delete_news_keyword, update_news_keyword
from app.models import NewsKeyword
from app.schemas import NewsKeywordCreate, NewsKeywordUpdate


class FakeSession:
    def __init__(self, row: NewsKeyword | None = None, lookup=None):
        self.row = row
        self.lookup = lookup
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, _query):
        return self.lookup

    def get(self, _model, keyword_id):
        return self.row if self.row and self.row.id == keyword_id else None

    def add(self, row):
        now = datetime.now(timezone.utc)
        row.id = row.id or 101
        row.created_at = row.created_at or now
        row.updated_at = row.updated_at or now
        self.row = row

    def commit(self):
        self.commits += 1
        if self.row:
            self.row.updated_at = datetime.now(timezone.utc)

    def refresh(self, _row):
        return None

    def rollback(self):
        self.rollbacks += 1


def keyword_row(**overrides) -> NewsKeyword:
    now = datetime.now(timezone.utc)
    values = {
        "id": 7,
        "keyword": "BBM langka",
        "is_active": True,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return NewsKeyword(**values)


def test_news_keyword_schema_normalizes_and_requires_changes():
    payload = NewsKeywordCreate(keyword="  mobil   tangki BBM  ")
    assert payload.keyword == "mobil tangki BBM"

    with pytest.raises(ValidationError):
        NewsKeywordUpdate()
    with pytest.raises(ValidationError):
        NewsKeywordCreate(keyword="   ")
    with pytest.raises(ValidationError):
        NewsKeywordUpdate(keyword=None)
    with pytest.raises(ValidationError):
        NewsKeywordUpdate(is_active=None)


def test_create_news_keyword_returns_admin_contract():
    db = FakeSession()
    result = create_news_keyword(NewsKeywordCreate(keyword="antrean SPBU"), db)

    assert result["id"] == 101
    assert result["keyword"] == "antrean SPBU"
    assert result["active"] is True
    assert db.commits == 1


def test_create_news_keyword_rejects_case_insensitive_duplicate():
    row = keyword_row()
    db = FakeSession(row=row, lookup=row)

    with pytest.raises(HTTPException) as raised:
        create_news_keyword(NewsKeywordCreate(keyword="bbm LANGKA"), db)

    assert raised.value.status_code == 409


def test_edit_and_delete_news_keyword_preserve_existing_articles_contract():
    row = keyword_row()
    db = FakeSession(row=row)

    updated = update_news_keyword(row.id, NewsKeywordUpdate(keyword="kelangkaan pertalite", is_active=False), db)
    assert updated["keyword"] == "kelangkaan pertalite"
    assert updated["active"] is False

    deleted = delete_news_keyword(row.id, db)
    assert deleted == {"id": 7, "deleted": True}
    assert row.is_active is False
    assert isinstance(row.deleted_at, datetime)
    assert row.deleted_at.tzinfo is not None


def test_create_news_keyword_restores_a_deleted_identity():
    row = keyword_row(is_active=False, deleted_at=datetime.now(timezone.utc))
    db = FakeSession(row=row, lookup=row)

    restored = create_news_keyword(NewsKeywordCreate(keyword="BBM langka"), db)

    assert restored["id"] == 7
    assert restored["active"] is True
    assert row.deleted_at is None
