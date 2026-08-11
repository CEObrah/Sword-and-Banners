"""Optional MCP transport for Sword. No Shinobi imports or cross-game loading."""
from __future__ import annotations
import os
from sword_runtime.api.app import _safe_player_context
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import SwordRuntime, RepositoryCommandPlanner

def build_mcp_server(root: str):
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError('install Sword service extras to enable MCP') from exc
    runtime=SwordRuntime(root); mcp=MCPServer('Sword & Banners')
    @mcp.tool()
    def sword_play_context():
        return _safe_player_context(runtime.store)
    @mcp.tool()
    def sword_preview_command(command: dict):
        c=CommandEnvelope.from_record(command); p=runtime.preview(c); return {'target_revision':c.expected_revision+1,'planning_reads':p.planning_reads,'writes':len(p.writes),'result':p.result}
    @mcp.tool()
    def sword_execute_command(command: dict):
        c=CommandEnvelope.from_record(command)
        if c.actor_id==RepositoryCommandPlanner.INTERNAL_ACTOR or c.mode!='gameplay': raise PermissionError('player MCP may not invoke internal/autonomous/maintenance actors')
        x=runtime.execute(c); return x.receipt.to_record() | {'status':x.status}
    return mcp
