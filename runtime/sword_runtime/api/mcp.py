"""Authenticated Streamable HTTP MCP surface for ChatGPT Projects."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

import anyio
import jwt
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import MCPServer as _LegacyGoldMCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict

from sword_runtime.api.operations import CampaignOperations, OperationError
from sword_runtime.commands import CommandEnvelope

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ALGORITHM = re.compile(r"^[A-Z0-9-]{3,16}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}$")
_PREVIEW_SECRET = re.compile(r"^[A-Za-z0-9_-]{43,256}$")
_MAX_TOKEN_BYTES = 16 * 1024
_PREVIEW_ATTESTATION_TTL_SECONDS = 300
_MAX_PREVIEW_ATTESTATION_BYTES = 1024

class _StrictToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ToolFailure(_StrictToolOutput):
    code: str
    retryable: bool
    refresh_context: bool

class ReadToolOutput(_StrictToolOutput):
    ok: bool
    result: Optional[dict[str, Any]] = None
    error: Optional[ToolFailure] = None

class PreviewToolOutput(_StrictToolOutput):
    ok: bool
    preview: Optional[dict[str, Any]] = None
    command: Optional[dict[str, Any]] = None
    preview_attestation: Optional[str] = None
    error: Optional[ToolFailure] = None

class ExecuteToolOutput(_StrictToolOutput):
    ok: bool
    receipt: Optional[dict[str, Any]] = None
    error: Optional[ToolFailure] = None

class _OpenAIToolSecuritySchemesMiddleware:
    """Mirror MCP auth metadata into ChatGPT's top-level tool extension."""
    async def __call__(self, context: Any, call_next: Any) -> Any:
        result = await call_next(context)
        if context.method != "tools/list" or result is None:
            return result
        if hasattr(result, "model_dump"):
            record = result.model_dump(by_alias=True, exclude_none=True)
        elif isinstance(result, Mapping):
            record = dict(result)
        else:
            return result
        tools = record.get("tools")
        if not isinstance(tools, list):
            return result
        for tool in tools:
            if not isinstance(tool, dict):
                return result
            metadata = tool.get("_meta")
            schemes = metadata.get("securitySchemes") if isinstance(metadata, dict) else None
            if not isinstance(schemes, list):
                return result
            tool["securitySchemes"] = schemes
        return record


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip() or value != value.strip():
        raise RuntimeError(f"{name} is required for MCP OAuth")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise RuntimeError(f"{name} contains invalid control characters")
    return value


def _https_url(value: str, name: str, *, exact_path: Optional[str] = None) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (exact_path is not None and parsed.path != exact_path)
    ):
        suffix = f" with path {exact_path}" if exact_path is not None else ""
        raise RuntimeError(f"{name} must be a public HTTPS URL{suffix}")
    return value


@dataclass(frozen=True)
class McpOAuthSettings:
    public_url: str
    issuer_url: str
    jwks_url: str
    audience: str
    algorithms: tuple[str, ...]
    read_scope: str
    write_scope: str
    allowed_subjects: tuple[str, ...]
    allowed_client_ids: tuple[str, ...]
    preview_secret: str = field(repr=False)
    allowed_origins: tuple[str, ...] = ("https://chatgpt.com", "https://chat.openai.com")

    @classmethod
    def from_env(cls) -> "McpOAuthSettings":
        public_url = _https_url(
            _required_env("SWORD_MCP_PUBLIC_URL"),
            "SWORD_MCP_PUBLIC_URL",
            exact_path="/mcp",
        )
        issuer_url = _https_url(
            _required_env("SWORD_OAUTH_ISSUER_URL"),
            "SWORD_OAUTH_ISSUER_URL",
        )
        jwks_url = _https_url(
            _required_env("SWORD_OAUTH_JWKS_URL"),
            "SWORD_OAUTH_JWKS_URL",
        )
        audience = _required_env("SWORD_OAUTH_AUDIENCE")
        algorithms = tuple(
            item.strip()
            for item in os.environ.get("SWORD_OAUTH_ALGORITHMS", "RS256").split(",")
            if item.strip()
        )
        if (
            not algorithms
            or len(algorithms) > 4
            or len(algorithms) != len(set(algorithms))
            or any(not _ALGORITHM.fullmatch(item) for item in algorithms)
            or "none" in {item.lower() for item in algorithms}
        ):
            raise RuntimeError("SWORD_OAUTH_ALGORITHMS is invalid")
        read_scope = os.environ.get("SWORD_OAUTH_READ_SCOPE", "sword:read")
        write_scope = os.environ.get("SWORD_OAUTH_WRITE_SCOPE", "sword:write")
        if not _SCOPE.fullmatch(read_scope) or not _SCOPE.fullmatch(write_scope):
            raise RuntimeError("Sword MCP OAuth scopes are invalid")
        allowed_subjects = tuple(
            item.strip()
            for item in _required_env("SWORD_OAUTH_ALLOWED_SUBJECTS").split(",")
            if item.strip()
        )
        if (
            not allowed_subjects
            or len(allowed_subjects) > 16
            or len(allowed_subjects) != len(set(allowed_subjects))
            or any(len(item) > 256 or any(c in item for c in ("\x00", "\r", "\n")) for item in allowed_subjects)
        ):
            raise RuntimeError("SWORD_OAUTH_ALLOWED_SUBJECTS is invalid")
        allowed_client_ids = tuple(
            item.strip()
            for item in os.environ.get("SWORD_OAUTH_ALLOWED_CLIENT_IDS", "").split(",")
            if item.strip()
        )
        if (
            len(allowed_client_ids) > 16
            or len(allowed_client_ids) != len(set(allowed_client_ids))
            or any(len(item) > 256 or any(c in item for c in ("\x00", "\r", "\n")) for item in allowed_client_ids)
        ):
            raise RuntimeError("SWORD_OAUTH_ALLOWED_CLIENT_IDS is invalid")
        preview_secret = _required_env("SWORD_MCP_PREVIEW_SECRET")
        if not _PREVIEW_SECRET.fullmatch(preview_secret):
            raise RuntimeError("SWORD_MCP_PREVIEW_SECRET must be 43..256 base64url characters")
        allowed_origins = tuple(
            item.strip()
            for item in os.environ.get(
                "SWORD_MCP_ALLOWED_ORIGINS",
                "https://chatgpt.com,https://chat.openai.com",
            ).split(",")
            if item.strip()
        )
        if not allowed_origins or any(
            urlparse(item).scheme != "https" or not urlparse(item).hostname
            for item in allowed_origins
        ):
            raise RuntimeError("SWORD_MCP_ALLOWED_ORIGINS is invalid")
        return cls(
            public_url=public_url,
            issuer_url=issuer_url,
            jwks_url=jwks_url,
            audience=audience,
            algorithms=algorithms,
            read_scope=read_scope,
            write_scope=write_scope,
            allowed_subjects=allowed_subjects,
            allowed_client_ids=allowed_client_ids,
            preview_secret=preview_secret,
            allowed_origins=allowed_origins,
        )

    @classmethod
    def optional_from_env(cls) -> Optional["McpOAuthSettings"]:
        names = (
            "SWORD_MCP_PUBLIC_URL",
            "SWORD_OAUTH_ISSUER_URL",
            "SWORD_OAUTH_JWKS_URL",
            "SWORD_OAUTH_AUDIENCE",
            "SWORD_OAUTH_ALLOWED_SUBJECTS",
            "SWORD_MCP_PREVIEW_SECRET",
        )
        present = [bool(os.environ.get(name)) for name in names]
        if not any(present):
            return None
        if not all(present):
            missing = [name for name, exists in zip(names, present) if not exists]
            raise RuntimeError("partial Sword MCP OAuth configuration; missing " + ", ".join(missing))
        return cls.from_env()


class JwtAccessTokenVerifier(TokenVerifier):
    """Verify bounded JWT access tokens against one configured JWKS endpoint."""
    def __init__(self, settings: McpOAuthSettings) -> None:
        self.settings = settings
        self._jwks = jwt.PyJWKClient(
            settings.jwks_url,
            cache_keys=True,
            lifespan=300,
            timeout=5,
        )

    def _verify_sync(self, token: str) -> Optional[AccessToken]:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer_url,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception:
            return None
        if not isinstance(claims, Mapping):
            return None
        raw_scope = claims.get("scope", claims.get("scp", ()))
        if isinstance(raw_scope, str):
            scopes = raw_scope.split()
        elif isinstance(raw_scope, Sequence) and not isinstance(raw_scope, (bytes, bytearray, str)):
            scopes = list(raw_scope)
        else:
            return None
        if (
            len(scopes) > 32
            or len(scopes) != len(set(scopes))
            or any(not isinstance(scope, str) or not _SCOPE.fullmatch(scope) for scope in scopes)
        ):
            return None
        client_id = claims.get("azp", claims.get("client_id", claims.get("sub")))
        subject = claims.get("sub")
        expires_at = claims.get("exp")
        if (
            not isinstance(client_id, str)
            or not client_id
            or not isinstance(subject, str)
            or not subject
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
        ):
            return None
        if subject not in self.settings.allowed_subjects:
            return None
        if self.settings.allowed_client_ids and client_id not in self.settings.allowed_client_ids:
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=self.settings.audience,
            subject=subject,
            claims={"iss": claims.get("iss"), "aud": claims.get("aud"), "sub": subject},
        )

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_BYTES:
            return None
        return await anyio.to_thread.run_sync(self._verify_sync, token)


def _validate_bounded_json(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 4096 or depth > 16:
        raise ValueError("JSON input exceeds bounded complexity")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 16 * 1024 or "\x00" in value:
            raise ValueError("JSON string is invalid")
        return
    if isinstance(value, list):
        if len(value) > 512:
            raise ValueError("JSON list is too large")
        for item in value:
            _validate_bounded_json(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict):
        if len(value) > 512:
            raise ValueError("JSON object is too large")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256 or "\x00" in key:
                raise ValueError("JSON key is invalid")
            _validate_bounded_json(item, depth=depth + 1, nodes=nodes)
        return
    raise ValueError("JSON value type is unsupported")


def _success(**values: Any) -> dict[str, Any]:
    return {"ok": True, **values}


def _failure(exc: OperationError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": exc.code,
            "retryable": exc.status_code >= 500 or exc.code == "stale_revision",
            "refresh_context": exc.code in {
                "stale_revision",
                "campaign_runtime_unavailable",
                "preview_attestation_invalid_or_expired",
            },
        },
    }


def _tool_call(call: Any) -> dict[str, Any]:
    try:
        value = call()
    except OperationError as exc:
        return _failure(exc)
    return _success(result=value)


def _require_write_scope(scope: str) -> Optional[dict[str, Any]]:
    token = get_access_token()
    if token is None or scope not in token.scopes:
        return _failure(OperationError(403, "oauth_write_scope_required"))
    return None


def _scope_challenge(oauth: McpOAuthSettings) -> CallToolResult:
    parsed = urlparse(oauth.public_url)
    metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource/mcp"
    challenge = (
        f'Bearer resource_metadata="{metadata_url}", '
        'error="insufficient_scope", '
        'error_description="The Sword campaign write scope is required", '
        f'scope="{oauth.read_scope} {oauth.write_scope}"'
    )
    return CallToolResult(
        content=[TextContent(text="Authentication with Sword campaign write access is required.")],
        structured_content=_failure(OperationError(403, "oauth_write_scope_required")),
        is_error=True,
        meta={"mcp/www_authenticate": [challenge]},
    )


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not value or len(value) > _MAX_PREVIEW_ATTESTATION_BYTES:
        raise ValueError("preview attestation segment is invalid")
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _preview_attestation(command: CommandEnvelope, oauth: McpOAuthSettings, *, now: Optional[int] = None) -> str:
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {
            "command_sha256": command.digest,
            "expires_at": issued_at + _PREVIEW_ATTESTATION_TTL_SECONDS,
            "version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(oauth.preview_secret.encode("ascii"), payload, hashlib.sha256).digest()
    return _b64url_encode(payload) + "." + _b64url_encode(signature)


def _verify_preview_attestation(
    command: CommandEnvelope,
    attestation: object,
    oauth: McpOAuthSettings,
    *,
    now: Optional[int] = None,
) -> bool:
    if (
        not isinstance(attestation, str)
        or not attestation
        or len(attestation) > _MAX_PREVIEW_ATTESTATION_BYTES
        or attestation.count(".") != 1
    ):
        return False
    try:
        payload_part, signature_part = attestation.split(".", 1)
        payload = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
        expected = hmac.new(oauth.preview_secret.encode("ascii"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict) or set(record) != {"command_sha256", "expires_at", "version"}:
        return False
    expires_at = record.get("expires_at")
    current = int(time.time()) if now is None else now
    return (
        record.get("version") == 1
        and record.get("command_sha256") == command.digest
        and isinstance(expires_at, int)
        and not isinstance(expires_at, bool)
        and current <= expires_at <= current + _PREVIEW_ATTESTATION_TTL_SECONDS
    )


def create_mcp_server(
    operations: CampaignOperations,
    oauth: McpOAuthSettings,
    *,
    token_verifier: Optional[TokenVerifier] = None,
) -> MCPServer:
    verifier = token_verifier or JwtAccessTokenVerifier(oauth)
    server = MCPServer(
        name="sword-and-banners",
        title="Sword & Banners Campaign",
        description="Private deterministic runtime for one persistent Warring States campaign.",
        instructions=(
            "Call get_play_context first for every live campaign turn. Use only player-visible "
            "returned facts and bounded exact-ID reads. Preview one currently supported semantic "
            "command, then pass the exact returned command and preview attestation to execute_command. "
            "Contested previews deliberately hide battle, duel, and siege-assault outcomes until the "
            "single execute. Narrate persistence only after a committed or duplicate receipt, then "
            "refresh context. OOC audit is read-only. Unsupported intent fails closed."
        ),
        version="0.2.0",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=oauth.issuer_url,
            resource_server_url=oauth.public_url,
            required_scopes=[oauth.read_scope],
        ),
        middleware=[_OpenAIToolSecuritySchemesMiddleware()],
    )
    read_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope]}]}
    write_security_meta = {"securitySchemes": [{"type": "oauth2", "scopes": [oauth.read_scope, oauth.write_scope]}]}
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="get_play_context",
        title="Get current play context",
        description="Required first live-play call. Returns bounded player-visible state, revision, scene, permitted IDs, and the current semantic command catalog.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_play_context() -> ReadToolOutput:
        return _tool_call(operations.play_context)

    @server.tool(
        name="get_person_sheet",
        title="Get one person sheet",
        description="Read one exact person ID permitted by fresh play context. The player gets the full logical sheet; other people return only bounded player-visible identity data.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def get_person_sheet(person_id: str) -> ReadToolOutput:
        if not isinstance(person_id, str) or len(person_id) > 128 or not _SAFE_ID.fullmatch(person_id):
            return _failure(OperationError(422, "person_id_invalid"))
        return _tool_call(lambda: operations.person_sheet(person_id))

    @server.tool(
        name="inspect_game_object",
        title="Inspect one game object",
        description="Read one exact object reference permitted by fresh play context. Repository paths and guessed hidden IDs are rejected.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def inspect_game_object(object_ref: str) -> ReadToolOutput:
        if not isinstance(object_ref, str) or len(object_ref) > 160 or not _SAFE_ID.fullmatch(object_ref):
            return _failure(OperationError(422, "object_ref_invalid"))
        return _tool_call(lambda: operations.inspect_game_object(object_ref))

    @server.tool(
        name="preview_command",
        title="Preview one campaign command",
        description=(
            "Read-only preview for one currently supported semantic command at the exact revision. "
            "Deterministic commands may return projected results. Contested commands return readiness "
            "only and hide the outcome. Both return an exact short-lived execution attestation."
        ),
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def preview_command(
        request_id: str,
        expected_revision: int,
        command_type: str,
        payload: dict[str, Any],
    ) -> PreviewToolOutput:
        if (
            not isinstance(request_id, str)
            or len(request_id) > 128
            or not _SAFE_ID.fullmatch(request_id)
            or not isinstance(command_type, str)
            or len(command_type) > 96
            or not _SAFE_ID.fullmatch(command_type)
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            return _failure(OperationError(422, "command_preview_input_invalid"))
        try:
            _validate_bounded_json(payload)
            context = operations.play_context()
            campaign = context["campaign"]
            if expected_revision != campaign["revision"]:
                raise OperationError(409, "stale_revision")
            if command_type not in set(context["commands"]["supported_command_types"]):
                raise OperationError(422, "unsupported_command_type")
            command = CommandEnvelope(
                campaign_id=campaign["campaign_id"],
                request_id=request_id,
                actor_id=campaign["player_id"],
                command_type=command_type,
                expected_revision=expected_revision,
                submitted_at=str(campaign["world_time"]),
                payload=payload,
                mode="gameplay",
            )
            preview = operations.preview_command(command)
        except OperationError as exc:
            return _failure(exc)
        except (TypeError, ValueError):
            return _failure(OperationError(422, "command_preview_input_invalid"))
        return _success(
            preview=preview,
            command=command.to_record(),
            preview_attestation=(
                _preview_attestation(command, oauth)
                if preview.get("status") in {"ready", "ready_execute_only"}
                else None
            ),
        )

    @server.tool(
        name="execute_command",
        title="Execute an exact previewed command",
        description="Write tool. Requires the exact complete previewed command plus its short-lived attestation. Exact already-committed retries may recover their immutable duplicate receipt.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=write_security_meta,
        structured_output=True,
    )
    def execute_command(
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
            existing = operations.lookup_command_receipt(envelope)
            if existing is not None:
                return _success(receipt=existing)
            if not _verify_preview_attestation(envelope, preview_attestation, oauth):
                raise OperationError(409, "preview_attestation_invalid_or_expired")
            receipt = operations.execute_command(envelope)
        except OperationError as exc:
            return _failure(exc)
        except (TypeError, ValueError):
            return _failure(OperationError(422, "invalid_command_envelope"))
        return _success(receipt=receipt)

    @server.tool(
        name="ooc_audit",
        title="Audit the game out of character",
        description="Read-only bounded runtime audit for OOC play observations and consistency review. It cannot mutate campaign state or authorize maintenance.",
        annotations=read_annotations,
        meta=read_security_meta,
        structured_output=True,
    )
    def ooc_audit(
        focus: Optional[str] = None,
        observations: Optional[list[str]] = None,
    ) -> ReadToolOutput:
        values = [] if observations is None else observations
        if (
            (focus is not None and (not focus or len(focus) > 512 or "\x00" in focus))
            or len(values) > 64
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > 2048
                or "\x00" in value
                for value in values
            )
        ):
            return _failure(OperationError(422, "ooc_input_invalid"))
        return _tool_call(lambda: operations.ooc_audit(focus, values))

    return server


def mount_mcp(
    app: FastAPI,
    server: MCPServer,
    oauth: McpOAuthSettings,
    *,
    max_request_body_size: int,
) -> None:
    """Mount stateless MCP at /mcp and compose its lifespan."""
    parsed = urlparse(oauth.public_url)
    host = parsed.netloc
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=max_request_body_size,
        host=parsed.hostname or host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, f"{parsed.hostname}:*"],
            allowed_origins=list(oauth.allowed_origins),
        ),
    )
    original_lifespan = app.router.lifespan_context
    mcp_lifespan = mcp_app.router.lifespan_context

    @app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
    def protected_resource_metadata() -> JSONResponse:
        return JSONResponse(
            {
                "resource": oauth.public_url,
                "authorization_servers": [oauth.issuer_url],
                "scopes_supported": [oauth.read_scope, oauth.write_scope],
                "bearer_methods_supported": ["header"],
            }
        )

    @asynccontextmanager
    async def combined_lifespan(parent: FastAPI):
        async with original_lifespan(parent):
            async with mcp_lifespan(mcp_app):
                yield

    app.router.lifespan_context = combined_lifespan
    app.mount("/", mcp_app, name="sword-mcp")
    app.state.mcp_server = server

# Backward-compatible local factory name retained for old imports. Production
# ChatGPT hosting uses create_mcp_server with explicit operations and OAuth.
def build_mcp_server(root: str):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    runtime = ProductionSwordRuntime(root)
    operations = CampaignOperations(runtime)
    oauth = McpOAuthSettings.from_env()
    return create_mcp_server(operations, oauth)

__all__ = [
    "JwtAccessTokenVerifier",
    "McpOAuthSettings",
    "build_mcp_server",
    "create_mcp_server",
    "mount_mcp",
    "_preview_attestation",
    "_verify_preview_attestation",
]
