"""Auto-send the final agent response back to Discord with retry."""

from agent import AgentContext, LoopData, UserMessage
from helpers.errors import format_error
from helpers.extension import Extension
from helpers.print_style import PrintStyle

from plugins._discord_integration.helpers.constants import (
    CTX_DC_ATTACHMENTS,
    CTX_DC_BOT,
    CTX_DC_KEYBOARD,
    CTX_DC_REPLY_TO,
    CTX_DC_TYPING_STOP,
)
from plugins._discord_integration.helpers.dependencies import ensure_dependencies


MAX_SEND_RETRIES: int = 2
CTX_SEND_FAILURES: str = "_discord_send_failures"


class DiscordAutoReply(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or self.agent.number != 0:
            return

        context = self.agent.context
        if not context.data.get(CTX_DC_BOT):
            return

        response_text = _extract_last_response(context)
        if not response_text:
            return

        attachments = context.data.pop(CTX_DC_ATTACHMENTS, [])
        keyboard = context.data.pop(CTX_DC_KEYBOARD, None)

        try:
            await self._send_reply(context, response_text, attachments, keyboard)
        except Exception as e:
            PrintStyle.error(f"Discord auto-reply error: {format_error(e)}")
        finally:
            typing_stop = context.data.pop(CTX_DC_TYPING_STOP, None)
            if typing_stop is not None:
                try:
                    typing_stop.set()
                except Exception:
                    pass
            context.data.pop(CTX_DC_REPLY_TO, None)

    async def _send_reply(
        self,
        context: AgentContext,
        response_text: str,
        attachments: list[str],
        keyboard: list[list[dict]] | None,
    ):
        ensure_dependencies()
        from plugins._discord_integration.helpers.handler import send_discord_reply

        error = await send_discord_reply(
            context, response_text, attachments or None, keyboard,
        )
        if not error:
            context.data[CTX_SEND_FAILURES] = 0
            return

        failures = context.data.get(CTX_SEND_FAILURES, 0) + 1
        context.data[CTX_SEND_FAILURES] = failures
        if failures <= MAX_SEND_RETRIES:
            _notify_agent_of_failure(context, error, failures)
        else:
            PrintStyle.error(
                f"Discord send failed {failures} times, giving up: {error}"
            )
            context.log.log(
                type="error",
                heading="Discord send failed (max retries reached)",
                content=error,
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_last_response(context: AgentContext) -> str:
    with context.log._lock:
        logs = list(context.log.logs)
    if not logs:
        return ""
    for item in reversed(logs):
        if item.type == "response":
            return item.content or ""
    return ""


def _notify_agent_of_failure(context: AgentContext, error: str, attempt: int):
    msg = context.agent0.read_prompt(
        "fw.discord.send_failed.md",
        error=error,
        attempt=str(attempt),
        max_retries=str(MAX_SEND_RETRIES),
    )
    context.log.log(type="error", heading="Discord send failed", content=error)
    context.communicate(UserMessage(message="", system_message=[msg]))
