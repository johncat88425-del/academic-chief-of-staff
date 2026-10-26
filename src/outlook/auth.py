"""Microsoft Graph API authentication via MSAL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import msal

from src.config import settings

SCOPES = [
    "Calendars.ReadWrite",
    "Mail.Read",
    "User.Read",
]

TOKEN_CACHE_PATH = Path("./data/.token_cache.json")


class OutlookAuth:
    """Manages OAuth 2.0 authentication for Microsoft Graph API."""

    def __init__(self):
        self._cache = msal.SerializableTokenCache()
        self._load_cache()
        self._app = msal.ConfidentialClientApplication(
            client_id=settings.azure_client_id,
            client_credential=settings.azure_client_secret,
            authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
            token_cache=self._cache,
        )

    def get_auth_url(self) -> str:
        """Generate the authorization URL for user login."""
        result = self._app.get_authorization_request_url(
            scopes=SCOPES,
            redirect_uri=settings.azure_redirect_uri,
        )
        return result

    def acquire_token_by_code(self, auth_code: str) -> dict:
        """Exchange authorization code for access token."""
        result = self._app.acquire_token_by_authorization_code(
            code=auth_code,
            scopes=SCOPES,
            redirect_uri=settings.azure_redirect_uri,
        )
        self._save_cache()
        return result

    def get_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if needed."""
        accounts = self._app.get_accounts()
        if not accounts:
            return None

        result = self._app.acquire_token_silent(
            scopes=SCOPES,
            account=accounts[0],
        )
        if result and "access_token" in result:
            self._save_cache()
            return result["access_token"]
        return None

    def is_authenticated(self) -> bool:
        """Check if we have valid credentials."""
        return self.get_access_token() is not None

    def _load_cache(self) -> None:
        """Load token cache from disk."""
        if TOKEN_CACHE_PATH.exists():
            self._cache.deserialize(TOKEN_CACHE_PATH.read_text())

    def _save_cache(self) -> None:
        """Persist token cache to disk."""
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_PATH.write_text(self._cache.serialize())
