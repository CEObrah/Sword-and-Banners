"""Additive MCP tools for bounded reads and narrow OOC maintenance."""
from __future__ import annotations

import re
from typing import Any, Optional

from mcp.types import ToolAnnotations

from sword_runtime.api.contract_guidance import enrich_command_contract
from sword_runtime.api.mcp import (
    ExecuteToolOutput,
    PreviewToolOutput,
    ReadToolOutput,
    _failure,
    _preview_attestation,
    _require_write_scope,
    _scope_challenge,
    _tool_call,
    _validate_bounded_json,
    _verify_preview_attestation,
)
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope

_SAFE_COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def install_extended_tools(server, operations, oauth) -> None:
    read_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope]}]}
    write_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope, oauth.write_scope]}]}
    read_annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(
        name="get_command_contract",
        title="Get one command contract",
        description="Read the exact player-facing payload contract and guidance for one semantic command currently advertised by fresh play context.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_command_contract(command_type: str) -> ReadToolOutput:
        if not isinstance(command_type, str) or not _SAFE_COMMAND.fullmatch(command_type):
            return _failure(OperationError(422, "command_type_invalid"))
        return _tool_call(lambda: enrich_command_contract(command_type, operations.get_command_contract(command_type)))

    @server.tool(
        name="list_controlled_formations",
        title="List controlled formations",
        description="Page through current player-controlled formations when the hot context is truncated. Continue with next_cursor; exact formation authority is revalidated on each read.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def list_controlled_formations(cursor: Optional[str] = None, limit: int = 20) -> ReadToolOutput:
        return _tool_call(lambda: operations.list_controlled_formations(cursor=cursor, limit=limit))

    @server.tool(
        name="list_known_information",
        title="List known information",
        description="Page through Tang Wei's saved known-information claims when the hot knowledge window is truncated. Continue with next_cursor; exact knower state remains authoritative.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def list_known_information(cursor: Optional[str] = None, limit: int = 20) -> ReadToolOutput:
        return _tool_call(lambda: operations.list_known_information(cursor=cursor, limit=limit))

    @server.tool(
        name="list_interaction_handles",
        title="List interaction handles",
        description="Page through player-visible triggered institutional/message interaction handles when the hot interaction window is truncated. Continue with next_cursor; these records establish only already-triggered player-visible facts.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def list_interaction_handles(cursor: Optional[str] = None, limit: int = 20) -> ReadToolOutput:
        return _tool_call(lambda: operations.list_interaction_handles(cursor=cursor, limit=limit))

    @server.tool(
        name="preview_qin_command_offer_scale_repair",
        title="Preview Qin offer scale repair",
        description=(
            "OOC DEV maintenance preview for the specific pending Qin field-command offer scale defect. "
            "It can only replace an oversized first command with the registered probationary detachment terms in Tang Wei's exact career owner."
        ),
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def preview_qin_command_offer_scale_repair(
        request_id: str,
        expected_revision: int,
        offer_ref: str,
    ) -> PreviewToolOutput:
        if (
            not isinstance(request_id, str)
            or len(request_id) > 128
            or not _SAFE_ID.fullmatch(request_id)
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
            or not isinstance(offer_ref, str)
            or not _SAFE_ID.fullmatch(offer_ref)
        ):
            return _failure(OperationError(422, "maintenance_repair_preview_input_invalid"))
        try:
            preview, command = operations.preview_qin_command_offer_scale_repair(request_id, expected_revision, offer_ref)
        except OperationError as exc:
            return _failure(exc)
        return {
            "ok": True,
            "preview": preview,
            "command": command.to_record(),
            "preview_attestation": _preview_attestation(command, oauth) if preview.get("status") in {"ready", "ready_execute_only"} else None,
        }

    @server.tool(
        name="execute_qin_command_offer_scale_repair",
        title="Execute Qin offer scale repair",
        description=(
            "OOC DEV write tool for the exact previewed Qin command-offer scale repair. "
            "Requires the canonical maintenance command and short-lived preview attestation."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
        meta=write_security_meta,
        structured_output=True,
    )
    def execute_qin_command_offer_scale_repair(
        command: dict[str, Any],
        preview_attestation: Optional[str] = None,
    ) -> ExecuteToolOutput:
        if _require_write_scope(oauth.write_scope) is not None:
            return _scope_challenge(oauth)  # type: ignore[return-value]
        try:
            _validate_bounded_json(command)
            envelope = CommandEnvelope.from_record(command)
            if envelope.to_record() != command:
                raise ValueError("command is not its canonical complete record")
            existing = operations.lookup_qin_command_offer_scale_repair_receipt(envelope)
            if existing is not None:
                return {"ok": True, "receipt": existing}
            if not _verify_preview_attestation(envelope, preview_attestation, oauth):
                raise OperationError(409, "preview_attestation_invalid_or_expired")
            receipt = operations.execute_qin_command_offer_scale_repair(envelope)
        except OperationError as exc:
            return _failure(exc)
        except (TypeError, ValueError):
            return _failure(OperationError(422, "invalid_maintenance_repair_envelope"))
        return {"ok": True, "receipt": receipt}


__all__ = ["install_extended_tools"]
