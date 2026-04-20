"""Fetch users.list for the allowlist picker in the UI."""

from helpers.api import ApiHandler, Request
from helpers.errors import format_error


class ListUsers(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler = input.get("handler", {}) or {}
        bot_token = (handler.get("bot_token") or "").strip()
        if not bot_token.startswith("xoxb-"):
            return {"success": False, "message": "Bot token required.", "users": []}
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from plugins._slack_integration.helpers import slack_client

            web = AsyncWebClient(token=bot_token)
            resp = await slack_client.users_list(web)
            if not resp.get("ok", False):
                return {
                    "success": False,
                    "message": resp.get("error", "unknown"),
                    "users": [],
                }
            users = []
            for u in resp.get("members", []) or []:
                if u.get("deleted") or u.get("is_bot"):
                    continue
                users.append({
                    "id": u.get("id", ""),
                    "name": (
                        u.get("real_name")
                        or u.get("profile", {}).get("display_name")
                        or u.get("name", "")
                    ),
                })
            return {"success": True, "users": users}
        except Exception as e:
            return {
                "success": False,
                "message": f"Could not list users: {format_error(e)}",
                "users": [],
            }
