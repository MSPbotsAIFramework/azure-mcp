# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Process-level settings. Tenant credentials are never read from here -- they
arrive per request as headers (see auth.py) and are never cached or persisted.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

TENANT_HEADER = "X-Azure-Tenant-Id"
CLIENT_ID_HEADER = "X-Azure-Client-Id"
CLIENT_SECRET_HEADER = "X-Azure-Client-Secret"

REQUIRED_HEADERS = [TENANT_HEADER, CLIENT_ID_HEADER, CLIENT_SECRET_HEADER]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Sovereign-cloud hook (Azure Government, China 21Vianet, Germany), unused
    # in v1 -- see the design doc's Non-goals. Overridable without a code
    # change if a future ticket asks for it.
    azure_ad_base_url: str = "https://login.microsoftonline.com"
    azure_arm_base_url: str = "https://management.azure.com"

    # Outbound HTTP behaviour (design doc Non-functional: 5s/30s, bounded
    # retry, <120s total call budget).
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3
    call_budget_seconds: float = 100.0


def get_settings() -> Settings:
    return Settings()
