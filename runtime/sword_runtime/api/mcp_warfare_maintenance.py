"""MCP publication for the explicit warfare/House/GBG scale repair."""
from __future__ import annotations

import re
from typing import Any, Optional

from mcp.types import ToolAnnotations

from sword_runtime.api.mcp import (
    ExecuteToolOutput,
    PreviewToolOutput,
    _failure,
    _preview_attestation,
    _require_write_scope,
    _scope_challenge,
    _validate_bounded_json,
    _verify_preview_attestation,
)
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def install_warfare_maintenance_tools(server, operations, oauth) -> None:
    read_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope]}]}
    write_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope, oauth.write_scope]}]}

    @server.tool(
        name="preview_warfare_house_scale_repair",
        title="Preview warfare and House scale repair",
        description=(
            "OOC DEV maintenance preview for the registered under-scaled warfare/House/Great Bow Guard repair. "
            "It derives exact changes from current campaign owners and stages no mutation during preview."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        meta=read_meta,
        structured_output=True,
    )
    def preview_warfare_house_scale_repair(request_id: str, expected_revision: int) -> PreviewToolOutput:
        if (
            not isinstance(request_id, str)
            or not _SAFE_ID.fullmatch(request_id)
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            return _failure(OperationError(422, "warfare_house_scale_repair_preview_input_invalid"))
        try:
            preview, command = operations.preview_warfare_house_scale_repair(request_id, expected_revision)
        except OperationError as exc:
            return _failure(exc)
        return {
            "ok": True,
            "preview": preview,
            "command": command.to_record(),
            "preview_attestation": _preview_attestation(command, oauth) if preview.get("status") in {"ready", "ready_execute_only"} else None,
        }

    @server.tool(
        name="execute_warfare_house_scale_repair",
        title="Execute warfare and House scale repair",
        description=(
            "OOC DEV write tool for the exact previewed registered warfare/House/Great Bow Guard scale repair. "
            "Requires the canonical maintenance command and short-lived preview attestation."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
        meta=write_meta,
        structured_output=True,
    )
    def execute_warfare_house_scale_repair(
        command: dict[str, Any], preview_attestation: Optional[str] = None
    ) -> ExecuteToolOutput:
        if _require_write_scope(oauth.write_scope) is not None:
            return _scope_challenge(oauth)  # type: ignore[return-value]
        try:
            _validate_bounded_json(command)
            envelope = CommandEnvelope.from_record(command)
            if envelope.to_record() != command:
                raise ValueError("command is not its canonical complete record")
            existing = operations.lookup_warfare_house_scale_repair_receipt(envelope)
            if existing is not None:
                return {"ok": True, "receipt": existing}
            if not _verify_preview_attestation(envelope, preview_attestation, oauth):
                raise OperationError(409, "preview_attestation_invalid_or_expired")
            receipt = operations.execute_warfare_house_scale_repair(envelope)
        except OperationError as exc:
            return _failure(exc)
        except (TypeError, ValueError):
            return _failure(OperationError(422, "invalid_warfare_house_scale_repair_envelope"))
        return {"ok": True, "receipt": receipt}


__all__ = ["install_warfare_maintenance_tools"]
