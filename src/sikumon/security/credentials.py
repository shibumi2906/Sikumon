"""Secure OpenAI credential storage."""

from __future__ import annotations

import os
from typing import Protocol

import keyring
from keyring.errors import KeyringError

KEYRING_SERVICE = "Sikumon"
KEYRING_OPENAI_ACCOUNT = "openai-api-key"


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def get_api_key(self) -> str | None: ...

    def set_api_key(self, api_key: str) -> None: ...

    def delete_api_key(self) -> None: ...


class KeyringCredentialStore:
    """Store production credentials in the operating-system credential vault."""

    def __init__(
        self,
        service: str = KEYRING_SERVICE,
        account: str = KEYRING_OPENAI_ACCOUNT,
        *,
        allow_environment_fallback: bool = True,
    ) -> None:
        self._service = service
        self._account = account
        self._allow_environment_fallback = allow_environment_fallback

    def get_api_key(self) -> str | None:
        try:
            stored = keyring.get_password(self._service, self._account)
        except KeyringError as error:
            raise CredentialStoreError("Unable to read the operating-system credential") from error
        if stored and stored.strip():
            return stored.strip()
        if not self._allow_environment_fallback:
            return None
        development_key = os.environ.get("OPENAI_API_KEY", "").strip()
        return development_key or None

    def set_api_key(self, api_key: str) -> None:
        normalized = api_key.strip()
        if not normalized:
            raise ValueError("API key cannot be empty")
        try:
            keyring.set_password(self._service, self._account, normalized)
        except KeyringError as error:
            raise CredentialStoreError("Unable to save the operating-system credential") from error

    def delete_api_key(self) -> None:
        try:
            existing = keyring.get_password(self._service, self._account)
            if existing is not None:
                keyring.delete_password(self._service, self._account)
        except KeyringError as error:
            raise CredentialStoreError("Unable to delete the operating-system credential") from error
