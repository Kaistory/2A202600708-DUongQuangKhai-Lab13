from __future__ import annotations

import os
from typing import Any

try:
    # Langfuse v3 API: `observe` lives on the top-level package and the old
    # `langfuse_context` singleton is replaced by the client from `get_client()`.
    from langfuse import get_client, observe

    class _Context:
        """Compatibility shim mapping the v2 `langfuse_context` calls onto the
        v3 client so the rest of the app does not need to change."""

        def update_current_trace(self, **kwargs: Any) -> None:
            try:
                get_client().update_current_trace(**kwargs)
            except Exception:  # pragma: no cover - never break the request path
                pass

        def update_current_observation(self, **kwargs: Any) -> None:
            client = get_client()
            try:
                client.update_current_span(**kwargs)
            except TypeError:
                # A span does not accept generation-only fields like usage_details.
                kwargs.pop("usage_details", None)
                try:
                    client.update_current_span(**kwargs)
                except Exception:  # pragma: no cover
                    pass
            except Exception:  # pragma: no cover
                pass

    langfuse_context = _Context()

except Exception:  # pragma: no cover
    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func
        return decorator

    class _DummyContext:
        def update_current_trace(self, **kwargs: Any) -> None:
            return None

        def update_current_observation(self, **kwargs: Any) -> None:
            return None

    langfuse_context = _DummyContext()


def tracing_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
