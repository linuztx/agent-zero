"""Test WhatsApp client connection status."""

from helpers.api import ApiHandler, Request


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler = input.get("handler", {})
        handler_name = handler.get("name", "")
        results: list[dict] = []

        try:
            from plugins._whatsapp_integration.helpers.handler import is_connected, _clients
            client = _clients.get(handler_name)

            if client and client.connected:
                me = client.me
                jid_str = ""
                if me:
                    jid_str = me.JID.User if me.JID else ""
                results.append({
                    "test": "Connection",
                    "ok": True,
                    "message": f"Connected as {jid_str}" if jid_str else "Connected",
                })
            else:
                results.append({
                    "test": "Connection",
                    "ok": False,
                    "message": "Not connected. Enable handler and scan QR code in settings.",
                })
        except Exception as e:
            from helpers.errors import format_error
            results.append({
                "test": "Connection",
                "ok": False,
                "message": format_error(e),
            })

        ok = all(r["ok"] for r in results)
        return {"success": ok, "results": results}
