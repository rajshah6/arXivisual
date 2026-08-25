"""Shared test configuration.

Keeps the test suite offline: disables Langfuse tracing so decorated pipeline
functions don't try to export spans to the network during unit tests. (A fuller
socket-blocking fixture is tracked in the backlog under Testing & CI.)
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
