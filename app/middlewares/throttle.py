import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, rate_seconds: float = 0.7) -> None:
        self.rate_seconds = rate_seconds
        self._last_hit = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            key = event.from_user.id
            now = time.monotonic()
            if now - self._last_hit[key] < self.rate_seconds:
                return
            self._last_hit[key] = now
        return await handler(event, data)
