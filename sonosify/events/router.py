import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sonosify.events.models import SonosEvent

type EventHandler[E: SonosEvent] = Callable[[E], Awaitable[None] | None]

_logger = logging.getLogger("sonosify.events")


class EventRouter:
    """Registry mapping event classes to handlers, dispatched by ``isinstance``."""

    def __init__(self) -> None:
        self._handlers: list[
            tuple[tuple[type[SonosEvent], ...], EventHandler[Any]]
        ] = []

    def on[E: SonosEvent](
        self, *events: type[E]
    ) -> Callable[[EventHandler[E]], EventHandler[E]]:
        """Register the decorated handler for the given event classes.

        Without arguments the handler receives every event; passing a base class
        such as ``SonosEvent`` has the same effect. Handlers may be sync or
        async and run in registration order, one event at a time.
        """
        selected = events or (SonosEvent,)

        def register(handler: EventHandler[E]) -> EventHandler[E]:
            self._handlers.append((selected, handler))
            return handler

        return register

    async def dispatch(self, event: SonosEvent) -> None:
        for selected, handler in self._handlers:
            if not isinstance(event, selected):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # A listener is meant to run for days: one broken handler must
                # not end the dispatch loop, and the remaining handlers still
                # need this event. Cancellation is a BaseException and passes.
                _logger.exception(
                    "event handler %s failed for %s event",
                    getattr(handler, "__qualname__", handler),
                    event.service,
                )
