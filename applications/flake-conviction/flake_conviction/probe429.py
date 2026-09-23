"""The SDK retries a concurrency 429 its own docstring says is never retried.
solari_core/_http.py gates retries on `status >= 500 or body.retryable is True`
and the gateway marks its concurrency refusal retryable, so an idempotent
request (every `create()` carries an Idempotency-Key) is sent six times with
backoff before the caller hears no. The SDK is handed a mock transport that
answers every request with that body, and the requests that reach it are
counted; no key, no network. crux PLATFORM.md D11 is the live measurement."""

import asyncio
import time
from importlib import metadata

import httpx

REFUSAL = {"code": "ConcurrencyLimitExceeded", "error": "Too many concurrent sessions",
           "retryable": True, "detail": "offline reproduction"}


async def count_offline(call) -> tuple[int, float, str]:
    """Requests that reached the transport, seconds taken, and what was raised."""
    from solari_sandbox import SandboxClient

    seen = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(429, json=REFUSAL)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with SandboxClient(api_key="offline", base_url="http://mock.invalid", http=http) as client:
        started = time.monotonic()
        try:
            await call(client)
        except Exception as exc:  # noqa: BLE001 - the refusal is the expected outcome
            raised = type(exc).__name__
        else:
            raised = "nothing"
        return seen, time.monotonic() - started, raised


def main_offline(say) -> int:
    say("sdk      " + ", ".join(f"{name} {metadata.version(name)}"
                                for name in ("solari-sandbox", "solari-core")))
    creates, seconds, raised = asyncio.run(count_offline(lambda c: c.create(template="base")))
    say(f"create   retryable 429: {creates} HTTP attempts, {seconds:.2f} s, raised {raised}")
    promotes, _, raised = asyncio.run(
        count_offline(lambda c: c.promote_snapshot("snap-offline", "offline")))
    say(f"promote  same body, no Idempotency-Key: {promotes} HTTP attempt(s), raised {raised}")
    if creates > 1:
        say(f"reproduced: the SDK documents a 429 as never retried and retried this one "
            f"{creates - 1} times")
        return 0
    say("not reproduced: the installed SDK sent the refused create once")
    return 1
