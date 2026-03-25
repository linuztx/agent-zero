"""Inject WhatsApp conversation context into system prompt for WhatsApp sessions."""

from helpers.extension import Extension
from agent import LoopData
from plugins._whatsapp_integration.helpers.handler import CTX_WA_HANDLER


class WhatsAppContextPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return

        if self.agent.context.data.get(CTX_WA_HANDLER):
            system_prompt.append(
                self.agent.read_prompt("fw.whatsapp.system_context_reply.md")
            )
