"""Intercept the response tool in Slack sessions for attachments and inline updates."""

from helpers.extension import Extension
from helpers.print_style import PrintStyle
from helpers.tool import Response

from plugins._slack_integration.helpers.routing import (
    CTX_SLACK_ATTACHMENTS,
    CTX_SLACK_CHANNEL_ID,
    CTX_SLACK_REPLY_IN_THREAD,
)


class SlackResponseIntercept(Extension):

    async def execute(
        self, tool_name: str = "", response: Response | None = None, **kwargs,
    ):
        if tool_name != "response":
            return
        if not self.agent:
            return
        context = self.agent.context
        if not context.data.get(CTX_SLACK_CHANNEL_ID):
            return

        tool = self.agent.loop_data.current_tool
        if not tool:
            return

        attachments = tool.args.get("attachments", [])
        if attachments:
            context.data[CTX_SLACK_ATTACHMENTS] = attachments

        in_thread = tool.args.get("in_thread", True)
        context.data[CTX_SLACK_REPLY_IN_THREAD] = bool(in_thread)

        agent_break = tool.args.get("break_loop", True)
        if agent_break is False and response:
            await self._send_inline(context, tool, response)

    async def _send_inline(self, context, tool, response: Response) -> None:
        from plugins._slack_integration.helpers.handler import send_slack_reply

        agent = self.agent
        assert agent is not None

        text = tool.args.get("text", tool.args.get("message", ""))
        attachments = context.data.pop(CTX_SLACK_ATTACHMENTS, [])
        in_thread = context.data.pop(CTX_SLACK_REPLY_IN_THREAD, True)

        if attachments:
            PrintStyle.info(f"Slack: sending update with {len(attachments)} attachment(s)")

        error = await send_slack_reply(
            context, text, attachments or None,
            in_thread=in_thread,
            keep_status=True,
        )

        if error:
            result = agent.read_prompt("fw.slack.update_error.md", error=error)
        else:
            result = agent.read_prompt("fw.slack.update_ok.md")

        response.break_loop = False
        response.message = result
        agent.hist_add_tool_result("response", result)
