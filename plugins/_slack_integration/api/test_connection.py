"""Test Slack connectivity: auth.test, Socket Mode handshake, scope presence."""

import asyncio

from helpers.api import ApiHandler, Request
from helpers.errors import format_error


REQUIRED_SCOPES = {
    "app_mentions:read",
    "channels:history",
    "chat:write",
    "files:write",
    "groups:history",
    "im:history",
    "mpim:history",
    "reactions:write",
    "users:read",
}


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler = input.get("handler", {}) or {}
        results: list[dict] = []

        bot_token = (handler.get("bot_token") or "").strip()
        app_token = (handler.get("app_token") or "").strip()

        await self._test_auth(bot_token, results)
        await self._test_scopes(bot_token, results)
        if app_token.startswith("xapp-"):
            await self._test_socket(app_token, bot_token, results)
        else:
            results.append({
                "test": "Socket Mode",
                "ok": False,
                "message": "App-level token must start with 'xapp-'.",
            })

        ok = all(r["ok"] for r in results)
        return {"success": ok, "results": results}

    async def _test_auth(self, bot_token: str, results: list[dict]) -> None:
        if not bot_token.startswith("xoxb-"):
            results.append({
                "test": "auth.test",
                "ok": False,
                "message": "Bot token must start with 'xoxb-'.",
            })
            return
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from plugins._slack_integration.helpers import slack_client

            web = AsyncWebClient(token=bot_token)
            info = await slack_client.auth_test(web)
            if info.get("ok", False):
                team = info.get("team", "")
                user = info.get("user", "")
                results.append({
                    "test": "auth.test",
                    "ok": True,
                    "message": f"Signed in as @{user} on {team}.",
                })
            else:
                results.append({
                    "test": "auth.test",
                    "ok": False,
                    "message": f"auth.test failed: {info.get('error', 'unknown')}",
                })
        except Exception as e:
            results.append({
                "test": "auth.test",
                "ok": False,
                "message": f"Could not call auth.test: {format_error(e)}",
            })

    async def _test_scopes(self, bot_token: str, results: list[dict]) -> None:
        if not bot_token.startswith("xoxb-"):
            return
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            web = AsyncWebClient(token=bot_token)
            resp = await web.auth_test()
            scopes_header = ""
            if resp and resp.headers:
                scopes_header = (
                    resp.headers.get("x-oauth-scopes")
                    or resp.headers.get("X-OAuth-Scopes")
                    or ""
                )
            scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
            missing = sorted(REQUIRED_SCOPES - scopes)
            if not scopes:
                results.append({
                    "test": "Scopes",
                    "ok": False,
                    "message": (
                        "Could not read the bot scopes. "
                        "Reinstall the app with the full scope list from the README."
                    ),
                })
                return
            if missing:
                results.append({
                    "test": "Scopes",
                    "ok": False,
                    "message": "Missing scopes: " + ", ".join(missing),
                })
            else:
                results.append({
                    "test": "Scopes",
                    "ok": True,
                    "message": "All required scopes granted.",
                })
        except Exception as e:
            results.append({
                "test": "Scopes",
                "ok": False,
                "message": f"Could not check scopes: {format_error(e)}",
            })

    async def _test_socket(
        self, app_token: str, bot_token: str, results: list[dict],
    ) -> None:
        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.web.async_client import AsyncWebClient

            client = SocketModeClient(
                app_token=app_token, web_client=AsyncWebClient(token=bot_token),
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

            results.append({
                "test": "Socket Mode",
                "ok": True,
                "message": "WebSocket handshake succeeded.",
            })
        except asyncio.TimeoutError:
            results.append({
                "test": "Socket Mode",
                "ok": False,
                "message": "Timed out while opening the Socket Mode connection.",
            })
        except Exception as e:
            results.append({
                "test": "Socket Mode",
                "ok": False,
                "message": f"Could not open Socket Mode: {format_error(e)}",
            })
