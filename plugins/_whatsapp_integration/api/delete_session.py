"""Delete WhatsApp session for a removed handler."""

from helpers.api import ApiHandler, Request


class DeleteSession(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler_name = input.get("handler_name", "")
        if not handler_name:
            return {"success": False, "message": "No handler name provided"}

        try:
            from plugins._whatsapp_integration.helpers.handler import (
                stop_client, remove_session,
            )

            await stop_client(handler_name, logout=True)
            remove_session(handler_name)
            return {"success": True, "message": f"Session removed for {handler_name}"}
        except Exception as e:
            from helpers.errors import format_error
            return {"success": False, "message": format_error(e)}
