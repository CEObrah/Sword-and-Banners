"""Additive MCP tools for bounded current reads and command discovery."""
from __future__ import annotations

import re
from typing import Optional

from mcp.types import ToolAnnotations

from sword_runtime.api.contract_guidance import enrich_command_contract
from sword_runtime.api.house_readiness import house_readiness_snapshot
from sword_runtime.api.mcp import ReadToolOutput, _failure, _tool_call
from sword_runtime.api.operations import OperationError

_SAFE_COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


def install_extended_tools(server, operations, oauth) -> None:
    read_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope]}]}
    read_annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(
        name="get_command_family",
        title="Get one command family",
        description="Demand-load the exact semantic operation names inside one intent family advertised by fresh play context. Then fetch only the selected operation contract.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_command_family(family: str) -> ReadToolOutput:
        if not isinstance(family, str) or not _SAFE_COMMAND.fullmatch(family):
            return _failure(OperationError(422, "command_family_invalid"))
        return _tool_call(lambda: operations.get_command_family(family))

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
        name="get_house_readiness",
        title="Get House Tang readiness",
        description="Read the current player-safe House Tang treasury, depot, armory, remount and realized replenishment picture without mutating or committing House resources.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_house_readiness() -> ReadToolOutput:
        return _tool_call(lambda: house_readiness_snapshot(operations))

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


__all__ = ["install_extended_tools"]
