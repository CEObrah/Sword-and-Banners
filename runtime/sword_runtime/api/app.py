"""Private authenticated HTTP service for one persistent Sword campaign."""
from __future__ import annotations
import os
import secrets
from pathlib import Path
from typing import Any, Optional
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sword_runtime.api.warfare_maintenance_operations import WarfareHouseMaintenanceOperations
from sword_runtime.api.middleware import BodySizeLimitMiddleware
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class CommandRequest(StrictModel):
    campaign_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=128)
    command_type: str = Field(min_length=1, max_length=96)
    expected_revision: int = Field(ge=0)
    submitted_at: str
    payload: dict[str, Any]
    mode: str = "gameplay"

class OocAuditRequest(StrictModel):
    focus: Optional[str] = Field(default=None, max_length=512)
    observations: list[str] = Field(default_factory=list, max_length=64)


def _safe_player_context(store) -> dict[str, Any]:
    """Compatibility helper retained for older tests and local callers."""
    runtime = type("ReadOnlyRuntime", (), {"store": store})()
    meta = store.read_json("state/meta.json")
    player = store.read_json("state/player.json")
    wallet = store.read_json("state/economy/player-wallet.json")
    scene = store.read_json("state/scene.json")
    known = []
    index = store.read_json("state/information/index.json")
    for _, path in sorted(index.get("claims", {}).items()):
        claim = store.read_json(path)
        if meta.get("player_id") in claim.get("knowers", []):
            known.append({
                "information_ref": claim.get("information_ref"),
                "claim": claim.get("claim"),
                "confidence": claim.get("confidence"),
                "provenance": claim.get("provenance"),
            })
    return {
        "campaign": {
            "campaign_id": meta["campaign_id"],
            "revision": meta["revision"],
            "world_time": meta["time"],
            "player_id": meta["player_id"],
        },
        "player": player,
        "wallet": wallet,
        "scene": scene,
        "known_information": known,
        "policy": "hidden state omitted unless lawfully known",
    }


def _domain_command(request: CommandRequest) -> CommandEnvelope:
    try:
        return CommandEnvelope(**request.model_dump())
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": "invalid_command_envelope"}) from exc


def create_app(
    root: object,
    token: str,
    runtime_root: object | None = None,
    *,
    recover: bool = False,
) -> FastAPI:
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("SWORD_API_TOKEN must be at least 32 characters")
    runtime = ProductionSwordRuntime(root, runtime_root)
    if recover:
        runtime.recover()
    operations = WarfareHouseMaintenanceOperations(runtime)
    app = FastAPI(
        title="Sword & Banners Runtime",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.sword_runtime = runtime
    app.state.campaign_operations = operations
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=128 * 1024)
    bearer = HTTPBearer(auto_error=False)

    async def auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(credentials.credentials, token)
        ):
            raise HTTPException(
                401,
                detail={"code": "unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/play/context", dependencies=[Depends(auth)])
    def context() -> dict[str, Any]:
        return operations.play_context()

    @app.get("/v1/person/{person_id}/sheet", dependencies=[Depends(auth)])
    def person_sheet(person_id: str) -> dict[str, Any]:
        try:
            return operations.person_sheet(person_id)
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.get("/v1/object/{object_ref}", dependencies=[Depends(auth)])
    def inspect_object(object_ref: str) -> dict[str, Any]:
        try:
            return operations.inspect_game_object(object_ref)
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.get("/v1/ooc/audit", dependencies=[Depends(auth)])
    def audit_compat() -> dict[str, Any]:
        return operations.ooc_audit()

    @app.post("/v1/ooc/audit", dependencies=[Depends(auth)])
    def audit(request: OocAuditRequest) -> dict[str, Any]:
        return operations.ooc_audit(request.focus, request.observations)

    @app.post("/v1/commands/preview", dependencies=[Depends(auth)])
    def preview(request: CommandRequest) -> dict[str, Any]:
        try:
            return operations.preview_command(_domain_command(request))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.post("/v1/commands/execute", dependencies=[Depends(auth)])
    def execute(request: CommandRequest) -> dict[str, Any]:
        try:
            return operations.execute_command(_domain_command(request))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc
    return app


def create_app_from_env() -> FastAPI:
    root = os.environ.get("SWORD_CAMPAIGN_ROOT")
    runtime_root = os.environ.get("SWORD_RUNTIME_ROOT")
    if not root or not runtime_root:
        raise RuntimeError("SWORD_CAMPAIGN_ROOT and SWORD_RUNTIME_ROOT are required")

    token = os.environ.get("SWORD_API_TOKEN") or secrets.token_urlsafe(48)
    app = create_app(Path(root), token, Path(runtime_root), recover=True)

    mcp_environment = (
        "SWORD_MCP_PUBLIC_URL",
        "SWORD_OAUTH_ISSUER_URL",
        "SWORD_OAUTH_JWKS_URL",
        "SWORD_OAUTH_AUDIENCE",
        "SWORD_OAUTH_ALLOWED_SUBJECTS",
        "SWORD_MCP_PREVIEW_SECRET",
    )
    if any(os.environ.get(name) for name in mcp_environment):
        from sword_runtime.api.mcp import McpOAuthSettings, create_mcp_server, mount_mcp
        from sword_runtime.api.mcp_extensions import install_extended_tools
        oauth = McpOAuthSettings.from_env()
        server = create_mcp_server(app.state.campaign_operations, oauth)
        install_extended_tools(server, app.state.campaign_operations, oauth)
        mount_mcp(
            app,
            server,
            oauth,
            max_request_body_size=128 * 1024,
        )
    return app

__all__ = ["create_app", "create_app_from_env", "_safe_player_context"]
