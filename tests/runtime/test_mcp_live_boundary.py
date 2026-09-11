"""Real MCP 2 HTTP/session/JSON boundary; only JWT verification is a test stub."""
import asyncio
import json

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier

from sword_runtime.api.app import create_app
from sword_runtime.api.mcp import McpOAuthSettings, create_mcp_server, mount_mcp
from sword_runtime.api.mcp_extensions import install_extended_tools
from sword_runtime.gm_skill_contract import GM_SKILL_CONTRACT_TOKEN
from test_gm_cognition_boundary import social_campaign


class TestVerifier(TokenVerifier):
    __test__ = False
    async def verify_token(self, token):
        if token != 'test-session-token':
            return None
        return AccessToken(token=token, client_id='local-test', scopes=['sword:read', 'sword:write'])


def test_actual_mcp_context_contract_preview_commit_retry(social_campaign, monkeypatch):
    # Explicit local environment: no claim to exercise Railway or external JWKS.
    for key in ('RAILWAY_GIT_COMMIT_SHA', 'RAILWAY_DEPLOYMENT_ID', 'RAILWAY_PROJECT_ID', 'RAILWAY_ENVIRONMENT_ID', 'RAILWAY_SERVICE_ID'):
        monkeypatch.delenv(key, raising=False)
    oauth = McpOAuthSettings(
        public_url='https://sword.test/mcp', issuer_url='https://issuer.test',
        jwks_url='https://issuer.test/jwks', audience='sword-test', algorithms=('RS256',),
        read_scope='sword:read', write_scope='sword:write', allowed_subjects=('test-subject',),
        allowed_client_ids=(), preview_secret='a' * 48,
    )
    app = create_app(social_campaign, 'a' * 48, social_campaign.parent / 'mcp-recovery')
    ops = app.state.campaign_operations
    server = create_mcp_server(ops, oauth, token_verifier=TestVerifier())
    install_extended_tools(server, ops, oauth)
    mount_mcp(app, server, oauth, max_request_body_size=128 * 1024)

    async def run():
        with anyio.fail_after(25):
            async with app.router.lifespan_context(app):
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app),
                    headers={'Authorization': 'Bearer test-session-token'},
                ) as http:
                    async with streamable_http_client(oauth.public_url, http_client=http) as streams:
                        async with ClientSession(streams[0], streams[1], read_timeout_seconds=15) as client:
                            await client.initialize()
                            listed = await client.list_tools()
                            tools = {tool.name: tool for tool in listed.tools}
                            assert {'get_play_context', 'preview_command', 'execute_command', 'get_command_contract'} <= tools.keys()
                            assert 'skill_contract_token' in tools['preview_command'].input_schema['properties']
                            async def call(name, arguments):
                                response = await client.call_tool(name, arguments)
                                assert not response.is_error, response
                                return response.structured_content
                            stale = await call('get_play_context', {'skill_contract_token': '0' * 64})
                            assert stale['error']['code'] == 'gm_skill_contract_mismatch'
                            valid = {'skill_contract_token': GM_SKILL_CONTRACT_TOKEN}
                            context = (await call('get_play_context', valid))['result']
                            integrity = context['delivery_integrity']
                            assert integrity['release_contract_sha256'] == GM_SKILL_CONTRACT_TOKEN
                            assert integrity['deployment_compatible'] is False
                            wrong = await call('get_play_context', {**valid, 'expected_campaign_id': 'another-campaign'})
                            assert wrong['error']['code'] == 'campaign_identity_mismatch'
                            contract = (await call('get_command_contract', {'command_type': 'scene_session_action'}))['result']
                            assert 'observation' in contract['input_guidance']['speech_kind']['allowed_values']
                            campaign = context['campaign']
                            args = {
                                **valid, 'expected_campaign_id': campaign['campaign_id'],
                                'request_id': 'mcp-close-once', 'expected_revision': campaign['revision'],
                                'command_type': 'scene_session_action',
                                'payload': {'action': 'close', 'session_ref': 'scene_session_cognition_test', 'close_reason': 'completed'},
                            }
                            invalid = await call('preview_command', {**args, 'skill_contract_token': '0' * 64})
                            assert invalid['error']['code'] == 'gm_skill_contract_mismatch'
                            preview = await call('preview_command', args)
                            assert preview['ok'], preview
                            assert ops.store.read_json('state/meta.json')['revision'] == campaign['revision']
                            execution = {'command': preview['command'], 'preview_attestation': preview['preview_attestation']}
                            committed = await call('execute_command', execution)
                            assert committed['ok'], committed
                            duplicate = await call('execute_command', {'command': preview['command']})
                            assert duplicate['receipt']['status'] == 'duplicate'
                            assert duplicate['receipt']['result'] == committed['receipt']['result']
                            refreshed = (await call('get_play_context', valid))['result']
                            assert refreshed['campaign']['revision'] == campaign['revision'] + 1
    asyncio.run(run())
