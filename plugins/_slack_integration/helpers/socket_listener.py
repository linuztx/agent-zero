"""Socket Mode listener lifecycle per handler."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from helpers.errors import format_error
from helpers.print_style import PrintStyle

from plugins._slack_integration.helpers import slack_client


@dataclass
class ListenerHandle:
    cfg_name: str
    task: asyncio.Task | None
    client: SocketModeClient
    web: AsyncWebClient
    bot_user_id: str
    team_id: str
    config_hash: str


def compute_config_hash(cfg: dict) -> str:
    """Hash fields whose change requires reconnecting."""
    material = {
        "bot_token": cfg.get("bot_token", ""),
        "app_token": cfg.get("app_token", ""),
        "listen_dm": cfg.get("listen_dm", True),
        "listen_channels": cfg.get("listen_channels", True),
        "allowed_channels": sorted(cfg.get("allowed_channels") or []),
        "allowed_users": sorted(cfg.get("allowed_users") or []),
        "denied_users": sorted(cfg.get("denied_users") or []),
    }
    blob = json.dumps(material, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


async def start_listener(cfg: dict) -> ListenerHandle | None:
    """Create a SocketModeClient, verify auth, connect. Returns None on failure."""
    name = cfg.get("name", "")
    bot_token = cfg.get("bot_token", "") or ""
    app_token = cfg.get("app_token", "") or ""
    if not bot_token or not app_token:
        PrintStyle.warning(f"Slack[{name}]: missing bot_token or app_token")
        return None

    web = AsyncWebClient(token=bot_token)
    try:
        auth = await slack_client.auth_test(web)
        if not auth.get("ok", False):
            PrintStyle.error(f"Slack[{name}]: auth.test failed: {auth.get('error')}")
            return None
    except Exception as e:
        PrintStyle.error(f"Slack[{name}]: auth.test error: {format_error(e)}")
        return None

    bot_user_id = auth.get("user_id", "") or ""
    team_id = auth.get("team_id", "") or ""

    client = SocketModeClient(app_token=app_token, web_client=web)

    async def _on_request(sm_client: SocketModeClient, req: SocketModeRequest) -> None:
        try:
            await sm_client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
        except Exception:
            pass

        if req.type != "events_api":
            return

        payload = req.payload or {}
        event = payload.get("event", {}) or {}
        event_type = event.get("type", "")
        if event_type not in {"message", "app_mention"}:
            return

        from plugins._slack_integration.helpers.handler import dispatch_event
        asyncio.create_task(dispatch_event(cfg, event, bot_user_id))

    client.socket_mode_request_listeners.append(_on_request)  # type: ignore[arg-type]

    try:
        await client.connect()
    except Exception as e:
        PrintStyle.error(f"Slack[{name}]: connect error: {format_error(e)}")
        return None

    PrintStyle.success(f"Slack[{name}]: connected (team={team_id}, bot={bot_user_id})")
    return ListenerHandle(
        cfg_name=name,
        task=None,
        client=client,
        web=web,
        bot_user_id=bot_user_id,
        team_id=team_id,
        config_hash=compute_config_hash(cfg),
    )


async def stop_listener(handle: ListenerHandle) -> None:
    try:
        await handle.client.disconnect()
    except Exception as e:
        PrintStyle.warning(f"Slack[{handle.cfg_name}]: disconnect error: {format_error(e)}")
    if handle.task and not handle.task.done():
        handle.task.cancel()
        try:
            await handle.task
        except (asyncio.CancelledError, Exception):
            pass
    PrintStyle.info(f"Slack[{handle.cfg_name}]: stopped")
