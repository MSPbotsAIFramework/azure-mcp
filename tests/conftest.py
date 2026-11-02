# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from azure_mcp import auth
from azure_mcp.server import create_mcp
from azure_mcp.settings import Settings

AD_BASE = "https://login.microsoftonline.com"
ARM_BASE = "https://management.azure.com"
TENANT_ID = "11111111-1111-1111-1111-111111111111"
TOKEN_URL = f"{AD_BASE}/{TENANT_ID}/oauth2/v2.0/token"


@pytest.fixture
def settings() -> Settings:
    # Keep retries fast in tests.
    return Settings(max_retries=2, call_budget_seconds=10)


@pytest.fixture
def mcp(settings):
    return create_mcp(settings)


@pytest.fixture
def creds():
    token = auth._current.set(
        auth.Credentials(
            tenant_id=TENANT_ID, client_id="test-client-id", client_secret="test-client-secret"
        )
    )
    yield
    auth._current.reset(token)


@pytest.fixture
def call(mcp):
    async def _call(tool: str, /, **args):
        result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return json.loads(blocks[0].text)

    return _call
