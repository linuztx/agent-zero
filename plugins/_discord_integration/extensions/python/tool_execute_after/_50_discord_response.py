"""Intercept the `response` tool in Discord sessions.

- Capture attachments and keyboard args for the final reply.
- If break_loop=False, send the update immediately and keep the loop running.
"""

from helpers.extension import Extension
from helpers.tool import Response

from plugins._discord_integration.helpers.constants import (
    CTX_DC_ATTACHMENTS,
    CTX_DC_BOT,
    CTX_DC_KEYBOARD,
)
from plugins._discord_integration.helpers.dependencies import ensure_dependencies


class DiscordResponseIntercept(Extension):

    async def execute(
        self, tool_name: str = "", response: Response | None = None, **kwargs,
    ):
        if tool_name != "response":
            return
        if not self.agent:
            return
        context = self.agent.context
        if not context.data.get(CTX_DC_BOT):
            return

        tool = self.agent.loop_data.current_tool
        if not tool:
            return

        attachments = tool.args.get("attachments", [])
        if attachments:
            context.data[CTX_DC_ATTACHMENTS] = attachments

        keyboard = tool.args.get("keyboard", None)
        if keyboard:
            context.data[CTX_DC_KEYBOARD] = keyboard

        agent_break = tool.args.get("break_loop", True)
        if agent_break is False and response is not None:
            await self._send_inline(context, tool, response)

    async def _send_inline(self, context, tool, response: Response):
        ensure_dependencies()
        from plugins._discord_integration.helpers.handler import send_discord_reply

        agent = self.agent
        assert agent is not None

        text = tool.args.get("text", tool.args.get("message", ""))
        attachments = context.data.pop(CTX_DC_ATTACHMENTS, [])
        keyboard = context.data.pop(CTX_DC_KEYBOARD, None)

        error = await send_discord_reply(context, text, attachments or None, keyboard)

        if error:
            result = agent.read_prompt("fw.discord.update_error.md", error=error)
        else:
            result = agent.read_prompt("fw.discord.update_ok.md")

        # Don't break loop — add the result to history so the agent sees outcome
        response.break_loop = False
        response.message = result
        agent.hist_add_tool_result("response", result)
