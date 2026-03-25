"""Serve QR code for WhatsApp authentication."""

import asyncio
import base64
import io

from helpers.api import ApiHandler, Request


class QrCode(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        handler_name = input.get("handler_name", "")

        try:
            from plugins._whatsapp_integration.helpers.handler import (
                get_qr_data, is_connected, get_handler_cfg,
                _client_tasks, client_lifecycle,
            )

            # Check handler is enabled (from request or saved config)
            handler_cfg = input.get("handler") or get_handler_cfg(handler_name)
            if not handler_cfg or not handler_cfg.get("enabled"):
                return {
                    "success": False,
                    "connected": False,
                    "qr_image": "",
                    "message": "Handler is not enabled. Enable and save first.",
                }

            if is_connected(handler_name):
                return {
                    "success": True,
                    "connected": True,
                    "qr_image": "",
                    "message": "Already connected",
                }

            # Start client lifecycle if not already running
            task = _client_tasks.get(handler_name)
            if not task or task.done():
                _client_tasks[handler_name] = asyncio.create_task(
                    client_lifecycle(handler_name, initial_cfg=handler_cfg)
                )
                # Wait briefly for QR to arrive
                for _ in range(20):
                    await asyncio.sleep(0.5)
                    if get_qr_data(handler_name) or is_connected(handler_name):
                        break

            if is_connected(handler_name):
                return {
                    "success": True,
                    "connected": True,
                    "qr_image": "",
                    "message": "Already connected",
                }

            qr_bytes = get_qr_data(handler_name)
            if not qr_bytes:
                return {
                    "success": False,
                    "connected": False,
                    "qr_image": "",
                    "message": "Waiting for QR code... Click again in a moment.",
                }

            import segno
            qr = segno.make_qr(qr_bytes)
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=8)
            qr_b64 = base64.b64encode(buf.getvalue()).decode()

            return {
                "success": True,
                "connected": False,
                "qr_image": qr_b64,
                "message": "Scan QR code with WhatsApp",
            }
        except Exception as e:
            from helpers.errors import format_error
            return {
                "success": False,
                "connected": False,
                "qr_image": "",
                "message": format_error(e),
            }
