from typing import Annotated

from fastapi import Header, HTTPException

from app.config import settings


def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings.internal_api_token.get_secret_value()
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Valid internal token required")
