from dataclasses import dataclass, field

from sigil.core.agent import Tool, ToolResult


@dataclass
class ScratchpadEntry:
    source: str
    message: str


@dataclass
class Scratchpad:
    _entries: list[ScratchpadEntry] = field(default_factory=list)

    def append(self, source: str, message: str) -> None:
        self._entries.append(ScratchpadEntry(source=source, message=message))

    def format_for_prompt(self) -> str:
        if not self._entries:
            return ""
        lines = ["## Cross-Agent Scratchpad", ""]
        for entry in self._entries:
            lines.append(f"- **{entry.source}**: {entry.message}")
        lines.append("")
        return "\n".join(lines)

    @property
    def entries(self) -> list[ScratchpadEntry]:
        return list(self._entries)

    def snapshot(self) -> str:
        return self.format_for_prompt()


def make_scratchpad_append_tool(scratchpad: Scratchpad, source: str) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        message = args.get("message", "").strip()
        if not message:
            return ToolResult(
                content="No message provided. Use the 'message' parameter to add a note."
            )
        scratchpad.append(source, message)
        return ToolResult(content=f"Note added to scratchpad from {source}.")

    return Tool(
        name="scratchpad_append",
        description=(
            "Add a brief note to the cross-agent scratchpad. Downstream agents "
            "(architect, engineer, auditor) will see your notes. Use this to "
            "leave observations, warnings, or key findings for later stages. "
            "Keep notes concise — one or two sentences per note."
        ),
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "A brief note to add to the scratchpad. Keep it concise.",
                },
            },
            "required": ["message"],
        },
        handler=_handler,
    )
