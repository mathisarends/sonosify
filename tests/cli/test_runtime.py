import asyncio
import inspect

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

import sonosify.cli.runtime as runtime_module
from sonosify.cli._dependencies import typer
from sonosify.cli.runtime import async_command, client_for
from sonosify.errors import SonosifyError


def test_async_command_awaits_handler_and_preserves_signature() -> None:
    @async_command
    async def handler(value: str, repeat: int = 1) -> str:
        await asyncio.sleep(0)
        return value * repeat

    assert inspect.signature(handler) == inspect.signature(handler.__wrapped__)
    assert handler("ok", repeat=2) == "okok"


def test_async_command_reports_sonosify_error_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @async_command
    async def handler() -> None:
        raise SonosifyError("boom")

    with pytest.raises(typer.Exit) as excinfo:
        handler()

    assert excinfo.value.exit_code == 1
    assert "boom" in capsys.readouterr().err


def test_client_for_resolves_target_and_yields_controller_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_resolve_target(room, ip):  # type: ignore[no-untyped-def]
        seen["resolve_args"] = (room, ip)
        return ("Kitchen", None)

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class _FakeController:
        def __init__(self, *, timeout: float) -> None:
            seen["timeout"] = timeout

        async def client(self, room, *, ip, coordinator):  # type: ignore[no-untyped-def]
            seen["client_args"] = (room, ip, coordinator)
            return _FakeClient()

    monkeypatch.setattr(runtime_module, "resolve_target", fake_resolve_target)
    monkeypatch.setattr(runtime_module, "SonosController", _FakeController)

    async def run() -> None:
        async with client_for("Office", None, coordinator=False) as client:
            assert isinstance(client, _FakeClient)

    asyncio.run(run())

    assert seen["resolve_args"] == ("Office", None)
    assert seen["client_args"] == ("Kitchen", None, False)
