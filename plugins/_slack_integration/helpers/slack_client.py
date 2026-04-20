"""Thin wrappers around slack_sdk's AsyncWebClient with retry-after handling.

All functions swallow non-fatal SlackApiError instances and return the
raw response `data` dict (so callers can inspect `ok` / `error` without
try/except chains). One retry on rate-limit (429) is honored, as the SDK
does not do this automatically for plain chat.postMessage calls.
"""

import asyncio
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient


async def _call_with_retry(coro_factory, *, max_retries: int = 1) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            resp = await coro_factory()
            return dict(resp.data) if resp and resp.data else {"ok": False, "error": "empty_response"}
        except SlackApiError as e:
            data = dict(e.response.data) if e.response and e.response.data else {}
            status = e.response.status_code if e.response else 0
            if status == 429 and attempt < max_retries:
                retry_after = int(e.response.headers.get("Retry-After", "1")) if e.response else 1
                await asyncio.sleep(max(1, retry_after))
                attempt += 1
                continue
            if "ok" not in data:
                data["ok"] = False
            if "error" not in data:
                data["error"] = str(e)
            return data


async def auth_test(web: AsyncWebClient) -> dict[str, Any]:
    return await _call_with_retry(lambda: web.auth_test())


async def post_message(
    web: AsyncWebClient,
    channel: str,
    text: str,
    thread_ts: str = "",
    mrkdwn: bool = True,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"channel": channel, "text": text, "mrkdwn": mrkdwn}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    return await _call_with_retry(lambda: web.chat_postMessage(**kwargs))


async def upload_file(
    web: AsyncWebClient,
    channel: str,
    file_path: str,
    filename: str = "",
    title: str = "",
    thread_ts: str = "",
    initial_comment: str = "",
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"channel": channel, "file": file_path}
    if filename:
        kwargs["filename"] = filename
    if title:
        kwargs["title"] = title
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    if initial_comment:
        kwargs["initial_comment"] = initial_comment
    return await _call_with_retry(lambda: web.files_upload_v2(**kwargs))


async def reactions_add(
    web: AsyncWebClient, channel: str, timestamp: str, name: str,
) -> dict[str, Any]:
    return await _call_with_retry(
        lambda: web.reactions_add(channel=channel, timestamp=timestamp, name=name)
    )


async def reactions_remove(
    web: AsyncWebClient, channel: str, timestamp: str, name: str,
) -> dict[str, Any]:
    # `no_reaction` is not an error in our flow — callers should ignore it.
    return await _call_with_retry(
        lambda: web.reactions_remove(channel=channel, timestamp=timestamp, name=name)
    )


async def conversations_info(web: AsyncWebClient, channel: str) -> dict[str, Any]:
    return await _call_with_retry(lambda: web.conversations_info(channel=channel))


async def users_info(web: AsyncWebClient, user: str) -> dict[str, Any]:
    return await _call_with_retry(lambda: web.users_info(user=user))


async def conversations_list(
    web: AsyncWebClient,
    types: str = "public_channel,private_channel,im,mpim",
    limit: int = 200,
) -> dict[str, Any]:
    return await _call_with_retry(
        lambda: web.conversations_list(types=types, limit=limit)
    )


async def users_list(web: AsyncWebClient, limit: int = 200) -> dict[str, Any]:
    return await _call_with_retry(lambda: web.users_list(limit=limit))
