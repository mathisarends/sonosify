import json
from pathlib import Path

from sonosify.cloud.cache_handler import CacheFileHandler, MemoryCacheHandler


def test_memory_cache_round_trip_and_clear() -> None:
    cache = MemoryCacheHandler({"accessToken": "initial"})

    assert cache.get_cached_token() == {"accessToken": "initial"}

    cache.save_token_to_cache({"accessToken": "updated"})
    assert cache.get_cached_token() == {"accessToken": "updated"}

    cache.clear_cached_token()
    assert cache.get_cached_token() is None


def test_file_cache_round_trip_and_permissions(tmp_path: Path) -> None:
    cache_path = tmp_path / "nested" / "token.json"
    cache = CacheFileHandler(cache_path)

    assert cache.get_cached_token() is None

    cache.save_token_to_cache({"accessToken": "token", "expiresIn": 3600})

    assert cache.get_cached_token() == {
        "accessToken": "token",
        "expiresIn": 3600,
    }
    assert json.loads(cache_path.read_text(encoding="utf-8"))["accessToken"] == "token"

    cache.clear_cached_token()
    assert not cache_path.exists()


def test_file_cache_rejects_malformed_or_non_object_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "token.json"
    cache = CacheFileHandler(cache_path)

    cache_path.write_text("not json", encoding="utf-8")
    assert cache.get_cached_token() is None

    cache_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cache.get_cached_token() is None
