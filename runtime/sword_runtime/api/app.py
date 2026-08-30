"""Private authenticated HTTP service for one persistent Sword campaign."""
from __future__ import annotations
from collections.abc import Mapping
import os
import secrets
from pathlib import Path
from typing import Any, Optional
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sword_runtime.api.sovereign_authority_operations import SovereignAuthorityAwareOperations
from sword_runtime.api.middleware import BodySizeLimitMiddleware
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope
from sword_runtime.deployment_attestation import assert_deployment_compatible, public_deployment_health
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


def _player_safe_transport(value: Any) -> Any:
    """Remove all GM-only backstage payloads from the generic REST transport.

    MCP is the GM surface and may receive bounded private cognition/director
    packets.  REST must redact both explicit ``gm_private*`` keys and mappings
    that declare themselves private through their ``privacy`` marker.  The
    latter matters for envelopes whose sensitive siblings have ordinary names,
    such as truthful hidden-motive dialogue guidance.
    """
    private = object()

    def scrub(item: Any) -> Any:
        if isinstance(item, Mapping):
            privacy = item.get("privacy")
            if isinstance(privacy, str) and privacy.startswith("gm_private"):
                return private
            out = {}
            for key, child in item.items():
                if isinstance(key, str) and key.startswith("gm_private"):
                    continue
                cleaned = scrub(child)
                if cleaned is private:
                    continue
                out[key] = cleaned
            return out
        if isinstance(item, list):
            out = []
            for child in item:
                cleaned = scrub(child)
                if cleaned is not private:
                    out.append(cleaned)
            return out
        if isinstance(item, tuple):
            out = []
            for child in item:
                cleaned = scrub(child)
                if cleaned is not private:
                    out.append(cleaned)
            return out
        return item

    cleaned = scrub(value)
    return {} if cleaned is private else cleaned


def _safe_player_context(store) -> dict[str, Any]:
    """Return the bounded read-only player context used by local callers."""
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
    campaign_root = Path(root).expanduser().resolve()
    runtime = ProductionSwordRuntime(campaign_root, runtime_root)
    if recover:
        runtime.recover()
    operations = SovereignAuthorityAwareOperations(runtime)
    app = FastAPI(
        title="Sword & Banners Runtime",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.sword_runtime = runtime
    app.state.campaign_operations = operations
    app.state.campaign_root = campaign_root
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
    def health() -> dict[str, Any]:
        return public_deployment_health(campaign_root)

    @app.get("/v1/play/context", dependencies=[Depends(auth)])
    def context() -> dict[str, Any]:
        return _player_safe_transport(operations.play_context())

    @app.get("/v1/person/{person_id}/sheet", dependencies=[Depends(auth)])
    def person_sheet(person_id: str) -> dict[str, Any]:
        try:
            return _player_safe_transport(operations.person_sheet(person_id))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.get("/v1/object/{object_ref}", dependencies=[Depends(auth)])
    def inspect_object(object_ref: str) -> dict[str, Any]:
        try:
            return _player_safe_transport(operations.inspect_game_object(object_ref))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.get("/v1/ooc/audit", dependencies=[Depends(auth)])
    def audit_get() -> dict[str, Any]:
        return operations.ooc_audit()

    @app.post("/v1/ooc/audit", dependencies=[Depends(auth)])
    def audit(request: OocAuditRequest) -> dict[str, Any]:
        return operations.ooc_audit(request.focus, request.observations)

    @app.post("/v1/commands/preview", dependencies=[Depends(auth)])
    def preview(request: CommandRequest) -> dict[str, Any]:
        try:
            return _player_safe_transport(operations.preview_command(_domain_command(request)))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc

    @app.post("/v1/commands/execute", dependencies=[Depends(auth)])
    def execute(request: CommandRequest) -> dict[str, Any]:
        try:
            return _player_safe_transport(operations.execute_command(_domain_command(request)))
        except OperationError as exc:
            raise HTTPException(exc.status_code, detail={"code": exc.code}) from exc
    return app


def create_app_from_env() -> FastAPI:
    root = os.environ.get("SWORD_CAMPAIGN_ROOT")
    runtime_root = os.environ.get("SWORD_RUNTIME_ROOT")
    if not root or not runtime_root:
        raise RuntimeError("SWORD_CAMPAIGN_ROOT and SWORD_RUNTIME_ROOT are required")

    campaign_root = Path(root)
    # Bootstrap has already fetched/reconciled the persistent checkout. Before
    # importing live campaign authority into an image, prove that the immutable
    # Railway build can safely execute that checkout. Runtime/game/dependency or
    # deployment-file drift fails startup instead of creating mixed-source play.
    assert_deployment_compatible(campaign_root)

    token = os.environ.get("SWORD_API_TOKEN") or secrets.token_urlsafe(48)
    app = create_app(campaign_root, token, Path(runtime_root), recover=True)

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


class _LazyEnvironmentApp:
    """Import-safe ASGI facade for production environments.

    Importing ``sword_runtime.api.app`` must not require Railway environment
    variables.  If this object is used as an ASGI application, the real app is
    constructed once from the current environment on first use.  Railway still
    uses ``api.entrypoint:app`` for eager startup/recovery.
    """

    def __init__(self) -> None:
        self._resolved: FastAPI | None = None

    def _get(self) -> FastAPI:
        if self._resolved is None:
            self._resolved = create_app_from_env()
        return self._resolved

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._get()(scope, receive, send)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


app = _LazyEnvironmentApp()

__all__ = ["app", "create_app", "create_app_from_env", "_safe_player_context", "_player_safe_transport"]