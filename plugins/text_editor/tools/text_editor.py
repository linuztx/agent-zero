import os

from python.helpers.tool import Tool, Response
from python.helpers.extension import call_extensions
from plugins.text_editor.helpers.file_ops import (
    get_config,
    read_file,
    write_file,
    validate_edits,
    apply_patch,
)


class TextEditor(Tool):

    async def execute(self, **kwargs):
        if self.method == "read":
            return await self._read(**kwargs)
        elif self.method == "write":
            return await self._write(**kwargs)
        elif self.method == "patch":
            return await self._patch(**kwargs)
        return Response(
            message=f"unknown method '{self.name}:{self.method}'",
            break_loop=False,
        )

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------
    async def _read(self, path: str = "", **kwargs) -> Response:
        if not path:
            return self._error("read", path, "path is required")

        cfg = get_config(self.agent)
        line_from = int(kwargs.get("line_from", 0))
        line_to = int(kwargs.get("line_to", 0))

        result = read_file(
            path,
            line_from=line_from,
            line_to=line_to,
            max_line_tokens=cfg["max_line_tokens"],
            default_line_count=cfg["default_line_count"],
            max_total_read_tokens=cfg["max_total_read_tokens"],
        )

        if result.error:
            return self._error("read", path, result.error)

        # Extension point
        ext_data = {"content": result.content, "warnings": result.warnings}
        await call_extensions(
            "text_editor_read_after", agent=self.agent, data=ext_data
        )

        msg = self.agent.read_prompt(
            "fw.text_editor.read_ok.md",
            path=os.path.expanduser(path),
            total_lines=str(result.total_lines),
            warnings=ext_data["warnings"],
            content=ext_data["content"],
        )
        return Response(message=msg, break_loop=False)

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------
    async def _write(self, path: str = "", content: str = "", **kwargs) -> Response:
        if not path:
            return self._error("write", path, "path is required")

        # Extension point
        ext_data = {"path": path, "content": content}
        await call_extensions(
            "text_editor_write_before", agent=self.agent, data=ext_data
        )

        result = write_file(ext_data["path"], ext_data["content"])

        if result.error:
            return self._error("write", path, result.error)

        # Extension point
        await call_extensions(
            "text_editor_write_after", agent=self.agent,
            data={"path": path, "total_lines": result.total_lines},
        )

        msg = self.agent.read_prompt(
            "fw.text_editor.write_ok.md",
            path=os.path.expanduser(path),
            total_lines=str(result.total_lines),
        )
        return Response(message=msg, break_loop=False)

    # ------------------------------------------------------------------
    # PATCH
    # ------------------------------------------------------------------
    async def _patch(self, path: str = "", edits=None, **kwargs) -> Response:
        if not path:
            return self._error("patch", path, "path is required")

        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            return self._error("patch", path, "file not found")

        parsed, err = validate_edits(edits)
        if err:
            return self._error("patch", path, err)

        # Extension point
        ext_data = {"path": expanded, "edits": parsed}
        await call_extensions(
            "text_editor_patch_before", agent=self.agent, data=ext_data
        )

        try:
            total_lines = apply_patch(ext_data["path"], ext_data["edits"])
        except Exception as exc:
            return self._error("patch", path, str(exc))

        # Extension point
        await call_extensions(
            "text_editor_patch_after", agent=self.agent,
            data={"path": expanded, "total_lines": total_lines},
        )

        msg = self.agent.read_prompt(
            "fw.text_editor.patch_ok.md",
            path=expanded,
            edit_count=str(len(ext_data["edits"])),
            total_lines=str(total_lines),
        )
        return Response(message=msg, break_loop=False)

    # ------------------------------------------------------------------
    # Shared error helper
    # ------------------------------------------------------------------
    def _error(self, action: str, path: str, error: str) -> Response:
        msg = self.agent.read_prompt(
            f"fw.text_editor.{action}_error.md", path=path, error=error
        )
        return Response(message=msg, break_loop=False)
