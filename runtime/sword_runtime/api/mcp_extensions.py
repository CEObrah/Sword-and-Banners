"""Small additive MCP surface for bounded rediscovery and exact command contracts."""
from __future__ import annotations

from mcp.types import ToolAnnotations

from sword_runtime.api.mcp import ReadToolOutput, _failure, _tool_call
from sword_runtime.api.operations import OperationError


def install_extended_tools(server, operations, oauth) -> None:
    read_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope]}]}
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="get_command_contract",
        title="Get one command contract",
        description="Read the exact player-facing payload contract and guidance for one semantic command currently advertised by fresh play context.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_command_contract(command_type: str) -> ReadToolOutput:
        if not isinstance(command_type, str) or not command_type or len(command_type) > 96:
            return _failure(OperationError(422, "command_type_invalid"))
        return _tool_call(lambda: operations.get_command_contract(command_type))

    @server.tool(
        name="list_controlled_formations",
        title="List controlled formations",
        description="Page through the player's current controlled formations when the bounded hot context is truncated. This is a read-only rediscovery surface; exact formation authority remains authoritative.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def list_controlled_formations(offset: int = 0, limit: int = 20) -> ReadToolOutput:
        if (
            isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 100000
            or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64
        ):
            return _failure(OperationError(422, "formation_page_invalid"))
        return _tool_call(lambda: operations.list_controlled_formations(offset=offset, limit=limit))


__all__ = ["install_extended_tools"]
