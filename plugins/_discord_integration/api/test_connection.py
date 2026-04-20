from helpers.api import ApiHandler, Request
from helpers.errors import format_error
from plugins._discord_integration.helpers.dependencies import ensure_dependencies


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        bot_cfg = input.get("bot", {})
        token = bot_cfg.get("token", "")
        results: list[dict] = []
        client_id = ""

        if not token:
            results.append({
                "test": "Bot token",
                "ok": False,
                "message": "Add your bot token first.",
            })
            return {"success": False, "results": results, "client_id": ""}

        try:
            ensure_dependencies()
            from plugins._discord_integration.helpers.bot_manager import test_token
            ok, message, client_id = await test_token(token)
            results.append({
                "test": "Discord bot",
                "ok": ok,
                "message": "Discord accepted the bot token." if ok else message,
            })
        except Exception as e:
            results.append({
                "test": "Discord bot",
                "ok": False,
                "message": f"Could not validate the bot token: {format_error(e)}",
            })

        return {
            "success": all(r["ok"] for r in results),
            "results": results,
            "client_id": client_id,
        }
