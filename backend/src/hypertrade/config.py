from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="HyperTrade", alias="APP_NAME")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=3334, alias="API_PORT")
    frontend_origin: str = Field(default="http://localhost:3333", alias="FRONTEND_ORIGIN")
    database_url: str = Field(
        default="postgresql+psycopg://hypertrade:hypertrade@postgres:5432/hypertrade",
        alias="DATABASE_URL",
    )

    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="hypertrade-admin", alias="ADMIN_PASSWORD")
    session_secret: str = Field(default="dev-session-secret-change-me", alias="SESSION_SECRET")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-v4-flash", alias="DEEPSEEK_MODEL")

    qwen_embedding_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_EMBEDDING_BASE_URL",
    )
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")
    qwen_embedding_model: str = Field(default="text-embedding-v4", alias="QWEN_EMBEDDING_MODEL")
    qwen_embedding_dimensions: int = Field(default=1024, alias="QWEN_EMBEDDING_DIMENSIONS")

    okx_api_key: str = Field(default="", alias="OKX_API_KEY")
    okx_api_secret: str = Field(default="", alias="OKX_API_SECRET")
    okx_passphrase: str = Field(default="", alias="OKX_PASSPHRASE")
    okx_testnet: bool = Field(default=True, alias="OKX_TESTNET")
    okx_public_ws_url: str = Field(
        default="wss://ws.okx.com:8443/ws/v5/public", alias="OKX_PUBLIC_WS_URL"
    )
    okx_rest_url: str = Field(default="https://www.okx.com", alias="OKX_REST_URL")
    okx_rest_supplement_interval_seconds: int = Field(
        default=300,
        alias="OKX_REST_SUPPLEMENT_INTERVAL_SECONDS",
    )
    paper_enabled: bool = Field(default=True, alias="PAPER_ENABLED")
    paper_loop_interval_seconds: int = Field(default=30, alias="PAPER_LOOP_INTERVAL_SECONDS")
    paper_starting_equity_usdt: str = Field(
        default="100000",
        alias="PAPER_STARTING_EQUITY_USDT",
    )
    paper_max_positions: int = Field(default=10, alias="PAPER_MAX_POSITIONS")
    paper_max_symbol_notional_pct: str = Field(
        default="0.20",
        alias="PAPER_MAX_SYMBOL_NOTIONAL_PCT",
    )
    paper_max_leverage: str = Field(default="5", alias="PAPER_MAX_LEVERAGE")
    paper_taker_fee_bps: str = Field(default="5", alias="PAPER_TAKER_FEE_BPS")
    paper_slippage_bps: str = Field(default="2", alias="PAPER_SLIPPAGE_BPS")

    feishu_webhook_url: str = Field(default="", alias="FEISHU_WEBHOOK_URL")
    monitor_scheduler_enabled: bool = Field(default=True, alias="MONITOR_SCHEDULER_ENABLED")
    monitor_loop_interval_seconds: int = Field(default=60, alias="MONITOR_LOOP_INTERVAL_SECONDS")
    agent_task_worker_enabled: bool = Field(default=True, alias="AGENT_TASK_WORKER_ENABLED")
    agent_task_poll_interval_seconds: float = Field(
        default=2.0,
        alias="AGENT_TASK_POLL_INTERVAL_SECONDS",
    )
    agent_task_lease_seconds: int = Field(default=60, alias="AGENT_TASK_LEASE_SECONDS")
    mission_runtime_enabled: bool = Field(default=False, alias="MISSION_RUNTIME_ENABLED")
    mission_runtime_canary_percent: int = Field(
        default=0,
        ge=0,
        le=100,
        alias="MISSION_RUNTIME_CANARY_PERCENT",
    )
    mission_runtime_worker_enabled: bool = Field(
        default=False,
        alias="MISSION_RUNTIME_WORKER_ENABLED",
    )
    mission_runtime_poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.25,
        le=60.0,
        alias="MISSION_RUNTIME_POLL_INTERVAL_SECONDS",
    )
    mission_runtime_lease_seconds: int = Field(
        default=60,
        ge=10,
        le=3_600,
        alias="MISSION_RUNTIME_LEASE_SECONDS",
    )
    operator_eval_fixtures_enabled: bool = Field(
        default=False,
        alias="HYPERTRADE_OPERATOR_EVAL_FIXTURES_ENABLED",
    )
    dynamic_team_enabled: bool = Field(default=False, alias="AGENT_DYNAMIC_TEAM_ENABLED")
    strategy_sandbox_enabled: bool = Field(default=False, alias="AGENT_STRATEGY_SANDBOX_ENABLED")
    strategy_sandbox_image: str = Field(default="", alias="AGENT_STRATEGY_SANDBOX_IMAGE")
    strategy_sandbox_socket_path: str = Field(
        default="/run/hypertrade-sandbox/runner.sock",
        alias="AGENT_STRATEGY_SANDBOX_SOCKET_PATH",
    )
    research_triggers_enabled: bool = Field(default=False, alias="RESEARCH_TRIGGERS_ENABLED")
    # The archive is the reproducible source for research verdicts. Pulling the window
    # live is opt-in: a verdict backed by a window that shifts under it is not evidence,
    # and an autonomous loop must not reach an exchange unless an operator asked it to.
    arc_evidence_live_fallback_enabled: bool = Field(
        default=False,
        alias="ARC_EVIDENCE_LIVE_FALLBACK_ENABLED",
    )
    # Declared origin of the mounted kline archive: "okx_swap", "alternative_exchange",
    # or empty/unspecified (reported as archive_unknown). The archive file carries no
    # provenance of its own, so an operator must declare what was seeded into it; ARC
    # refuses to spend a candidate budget on non-OKX evidence unless the mission was
    # created with alternative_source_confirmed=true.
    arc_evidence_archive_origin: str = Field(
        default="",
        alias="ARC_EVIDENCE_ARCHIVE_ORIGIN",
    )
    # Provider hypothesis channel for ARC missions. Opt-in like the live evidence
    # fallback: a loop calling a paid model on its own initiative is a side effect,
    # so production enables this explicitly once the canary contract allows it.
    arc_provider_hypotheses_enabled: bool = Field(
        default=False,
        alias="ARC_PROVIDER_HYPOTHESES_ENABLED",
    )
    # Hashed service principals only. Format: label:arc:read+arc:start:sha256hex, comma-separated.
    # No token value can carry an approve capability; approval is not a token scope.
    arc_service_tokens: str = Field(default="", alias="ARC_SERVICE_TOKENS")
    # Shared HMAC key with BitPro. Empty refuses every signed assertion (fail closed).
    # Must be distinct from SESSION_SECRET and must live in the server env, never the repo.
    arc_operator_assertion_secret: str = Field(
        default="",
        alias="ARC_OPERATOR_ASSERTION_SECRET",
    )
    arc_operator_assertion_max_age_seconds: int = Field(
        default=300,
        alias="ARC_OPERATOR_ASSERTION_MAX_AGE_SECONDS",
    )
    research_trigger_poll_interval_seconds: float = Field(
        default=10.0,
        alias="RESEARCH_TRIGGER_POLL_INTERVAL_SECONDS",
    )
    research_trigger_lease_seconds: int = Field(
        default=60,
        alias="RESEARCH_TRIGGER_LEASE_SECONDS",
    )
    research_trigger_global_daily_quota: int = Field(
        default=20,
        alias="RESEARCH_TRIGGER_GLOBAL_DAILY_QUOTA",
    )
    rag_scan_interval_seconds: int = Field(default=600, alias="RAG_SCAN_INTERVAL_SECONDS")
    knowledge_dir: Path = Field(default=Path("docs/knowledge"), alias="KNOWLEDGE_DIR")
    raw_market_retention_days: int = Field(default=7, alias="RAW_MARKET_RETENTION_DAYS")
    llm_daily_soft_budget_usd: float = Field(default=5.0, alias="LLM_DAILY_SOFT_BUDGET_USD")
    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str = Field(default="", alias="LANGFUSE_BASE_URL")
    skill_eval_attestation_secret: str = Field(
        default="",
        alias="SKILL_EVAL_ATTESTATION_SECRET",
    )
    agent_tool_timeout_quick_seconds: float = Field(
        default=5.0,
        alias="AGENT_TOOL_TIMEOUT_QUICK_SECONDS",
    )
    agent_tool_timeout_standard_seconds: float = Field(
        default=30.0,
        alias="AGENT_TOOL_TIMEOUT_STANDARD_SECONDS",
    )
    agent_tool_timeout_long_seconds: float = Field(
        default=120.0,
        alias="AGENT_TOOL_TIMEOUT_LONG_SECONDS",
    )
    bitpro_sqlite_path: Path = Field(default=Path(""), alias="BITPRO_SQLITE_PATH")
    bitpro_mcp_api_base: str = Field(
        default="http://127.0.0.1:8889/api/v2",
        alias="BITPRO_MCP_API_BASE",
    )
    bitpro_mcp_api_token: str = Field(default="", alias="BITPRO_MCP_API_TOKEN")
    bitpro_remote_mcp_url: str = Field(default="", alias="BITPRO_REMOTE_MCP_URL")
    bitpro_mcp_auth_header: str = Field(
        default="X-BitPro-MCP-Token",
        alias="BITPRO_MCP_AUTH_HEADER",
    )
    bitpro_mcp_timeout_seconds: float = Field(
        default=15.0,
        alias="BITPRO_MCP_TIMEOUT_SECONDS",
    )
    active_chat_provider: str = Field(default="deepseek", alias="ACTIVE_CHAT_PROVIDER")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    codex_base_url: str = Field(
        default="https://chatgpt.com/backend-api/codex",
        alias="CODEX_BASE_URL",
    )
    codex_api_key: str = Field(default="", alias="CODEX_API_KEY")
    codex_auth_json: Path = Field(
        default_factory=lambda: Path.home() / ".codex" / "auth.json",
        alias="CODEX_AUTH_JSON",
    )
    codex_model: str = Field(default="gpt-5.4", alias="CODEX_MODEL")
    codex_model_options: str = Field(
        default="gpt-5.4,gpt-5.5,gpt-5.4-mini",
        alias="CODEX_MODEL_OPTIONS",
    )
    codex_timeout_seconds: float = Field(default=90.0, alias="CODEX_TIMEOUT_SECONDS")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="", alias="OPENROUTER_MODEL")
    qwen_chat_model: str = Field(default="qwen-plus", alias="QWEN_CHAT_MODEL")
    vide_coding_base_url: str = Field(
        default="https://api.vide.ai/v1",
        alias="VIDE_CODING_BASE_URL",
    )
    vide_coding_api_key: str = Field(default="", alias="VIDE_CODING_API_KEY")
    vide_coding_model: str = Field(default="opus-4.6", alias="VIDE_CODING_MODEL")
    risk_max_order_notional_usdt: str = Field(
        default="100",
        alias="RISK_MAX_ORDER_NOTIONAL_USDT",
    )
    risk_max_open_intents: int = Field(default=5, alias="RISK_MAX_OPEN_INTENTS")
    world_model_defensive_actions_enabled: bool = Field(
        default=False,
        alias="WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED",
    )
    world_model_defensive_action_allowlist: str = Field(
        default="",
        alias="WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
