"""Auto-send Slack reply when agent responds in a Slack session."""

import asyncio

from agent import AgentContext, LoopData, UserMessage
from helpers.extension import Extension
from helpers.print_style import PrintStyle

from plugins._slack_integration.helpers.routing import (
    CTX_SLACK_ATTACHMENTS,
    CTX_SLACK_CHANNEL_ID,
    CTX_SLACK_REPLY_IN_THREAD,
)


MAX_SEND_RETRIES: int = 2
CTX_SEND_FAILURES: str = "_slack_send_failures"


class SlackAutoReply(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or self.agent.number != 0:
            return

        context = self.agent.context
        if not context.data.get(CTX_SLACK_CHANNEL_ID):
            return

        response_text = _extract_last_response(context)
        if not response_text:
            return

        attachments = context.data.pop(CTX_SLACK_ATTACHMENTS, [])
        in_thread = context.data.pop(CTX_SLACK_REPLY_IN_THREAD, True)
        if attachments:
            PrintStyle.info(f"Slack: sending reply with {len(attachments)} attachment(s)")
        asyncio.create_task(self._send_reply(context, response_text, attachments, in_thread))

    async def _send_reply(
        self, context: AgentContext, response_text: str,
        attachments: list[str], in_thread: bool,
    ):
        from plugins._slack_integration.helpers.handler import send_slack_reply

        error = await send_slack_reply(
            context, response_text, attachments,
            in_thread=in_thread, keep_status=False,
        )
        if not error:
            context.data[CTX_SEND_FAILURES] = 0
            return
        failures = context.data.get(CTX_SEND_FAILURES, 0) + 1
        context.data[CTX_SEND_FAILURES] = failures
        if failures <= MAX_SEND_RETRIES:
            _notify_agent_of_failure(context, error, failures)
        else:
            PrintStyle.error(f"Slack send failed {failures} times, giving up: {error}")
            context.log.log(
                type="error",
                heading="Slack send failed (max retries reached)",
                content=error,
            )


def _extract_last_response(context: AgentContext) -> str:
    with context.log._lock:
        logs = list(context.log.logs)
    if not logs:
        return ""
    for item in reversed(logs):
        if item.type == "response":
            return item.content or ""
    return ""


def _notify_agent_of_failure(context: AgentContext, error: str, attempt: int) -> None:
    msg = context.agent0.read_prompt(
        "fw.slack.send_failed.md",
        error=error,
        attempt=str(attempt),
        max_retries=str(MAX_SEND_RETRIES),
    )
    context.log.log(type="error", heading="Slack send failed", content=error)
    context.communicate(UserMessage(message="", system_message=[msg]))
