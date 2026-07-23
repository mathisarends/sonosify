import asyncio

import pytest

from sonosify import Favorite, SonosClient


class _Client(SonosClient):
    def __init__(self) -> None:
        super().__init__("127.0.0.1")
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def close(self) -> None:
        return None

    async def play_uri(self, uri: str, *, title: str = "", radio: bool = False) -> None:
        self.calls.append(("play_uri", {"uri": uri, "title": title, "radio": radio}))

    async def open_favorite(self, favorite: Favorite) -> None:
        self.calls.append(("open_favorite", {"title": favorite.title}))


def test_open_dispatches_favorite() -> None:
    client = _Client()
    favorite = Favorite(title="Jazz", uri="x-rincon-cpcontainer:...")

    position = asyncio.run(client.open(favorite))

    assert position is None
    assert client.calls == [("open_favorite", {"title": "Jazz"})]


def test_open_falls_back_to_play_uri() -> None:
    client = _Client()

    position = asyncio.run(
        client.open("https://example.com/live.mp3", title="Radio", radio=True)
    )

    assert position is None
    assert client.calls == [
        (
            "play_uri",
            {"uri": "https://example.com/live.mp3", "title": "Radio", "radio": True},
        )
    ]


def test_client_identity_is_read_only() -> None:
    client = SonosClient("127.0.0.1", port=1400, uid="RINCON_1")

    assert (client.ip, client.port, client.uid) == ("127.0.0.1", 1400, "RINCON_1")
    with pytest.raises(AttributeError):
        client.ip = "127.0.0.2"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        client.unexpected = True  # type: ignore[attr-defined]

    asyncio.run(client.close())
