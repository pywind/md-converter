"""Execution helpers bridging synchronous services into async contexts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_sync(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Execute *func* in a worker thread and return the result."""

    return await asyncio.to_thread(func, *args, **kwargs)


__all__ = ["run_sync"]
