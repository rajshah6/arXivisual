"""Lazy, cached Temporal client for the API process.

The API only ever *starts* workflows — all execution happens on the worker
Container App. Kept in its own module so importing routes never touches
Temporal when USE_TEMPORAL is off.
"""

from __future__ import annotations

import os

from temporalio.client import Client

_client: Client | None = None


def temporal_enabled() -> bool:
    return os.getenv("USE_TEMPORAL", "0") == "1"


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
        )
    return _client
