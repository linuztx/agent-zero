"""Fetch conversations.list for the allowlist picker in the UI."""

from helpers.api import ApiHandler, Request
from helpers.errors import format_error


class ListChannels(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler = input.get("handler", {}) or {}
        bot_token = (handler.get("bot_token") or "").strip()
        if not bot_token.startswith("xoxb-"):
            return {"success": False, "message": "Bot token required.", "channels": []}
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from plugins._slack_integration.helpers import slack_client

            web = AsyncWebClient(token=bot_token)
            resp = await slack_client.conversations_list(web)
            if not resp.get("ok", False):
                return {
                    "success": False,
                    "message": resp.get("error", "unknown"),
                    "channels": [],
                }
            channels = []
            for c in resp.get("channels", []) or []:
                channels.append({
                    "id": c.get("id", ""),
                    "name": c.get("name") or (f"DM {c.get('user','')}" if c.get("is_im") else ""),
                    "is_private": bool(c.get("is_private")),
                    "is_im": bool(c.get("is_im")),
                    "is_member": bool(c.get("is_member")),
                })
            return {"success": True, "channels": channels}
        except Exception as e:
            return {
                "success": False,
                "message": f"Could not list channels: {format_error(e)}",
                "channels": [],
            }
