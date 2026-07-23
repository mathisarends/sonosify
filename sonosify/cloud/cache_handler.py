import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


class CacheHandler(ABC):
    @abstractmethod
    def get_cached_token(self) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        raise NotImplementedError

    def clear_cached_token(self) -> None:
        self.save_token_to_cache({})


class MemoryCacheHandler(CacheHandler):
    def __init__(self, token_info: dict[str, Any] | None = None) -> None:
        self._token_info = token_info

    def get_cached_token(self) -> dict[str, Any] | None:
        _logger.debug("Reading token from memory cache")
        return self._token_info

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        _logger.debug("Saving token to memory cache")
        self._token_info = token_info

    def clear_cached_token(self) -> None:
        _logger.debug("Clearing token from memory cache")
        self._token_info = None


class CacheFileHandler(CacheHandler):
    def __init__(self, cache_path: str | Path = ".cache") -> None:
        self.cache_path = Path(cache_path)

    def get_cached_token(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            _logger.debug("Token cache file does not exist: path=%s", self.cache_path)
            return None
        try:
            token_info = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _logger.warning(
                "Unable to read token cache file: path=%s",
                self.cache_path,
                exc_info=True,
            )
            return None
        if not isinstance(token_info, dict):
            _logger.warning(
                "Token cache file does not contain an object: path=%s",
                self.cache_path,
            )
            return None
        _logger.debug("Read token from cache file: path=%s", self.cache_path)
        return token_info

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(token_info, indent=2),
                encoding="utf-8",
            )
            if os.name != "nt":
                self.cache_path.chmod(0o600)
        except OSError:
            _logger.exception(
                "Unable to save token cache file: path=%s",
                self.cache_path,
            )
            raise
        _logger.debug("Saved token to cache file: path=%s", self.cache_path)

    def clear_cached_token(self) -> None:
        try:
            self.cache_path.unlink(missing_ok=True)
        except OSError:
            _logger.exception(
                "Unable to remove token cache file: path=%s",
                self.cache_path,
            )
            raise
        _logger.debug("Removed token cache file: path=%s", self.cache_path)
