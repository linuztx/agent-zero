from helpers.extension import Extension
from plugins._context_window.helpers.usage import add_prompt


class RecordMcpInstructionsUsage(Extension):
    def execute(self, data: dict | None = None, **kwargs):
        add_prompt(
            self.agent,
            "mcp_tools",
            (data or {}).get("result"),
            source="mcp_instructions",
        )
