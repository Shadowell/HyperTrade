// Shared shapes of the operator console API payloads and UI state.

export type Language = "zh" | "en";
export type ThemeMode = "dark" | "light";
export type NavSection = "harness" | "missions" | "knowledge" | "system";

export type TraceEvent = {
  id?: string;
  tool_name: string;
  status: string;
  created_at?: string;
  input_json?: Record<string, unknown>;
  output_json?: Record<string, unknown>;
};

export type AgentRun = {
  id: string;
  status: string;
  report_markdown: string;
  report_json?: Record<string, unknown>;
  run_state_json?: {
    current_node?: string;
  };
  trace_events: TraceEvent[];
};

export type RunSummary = {
  id: string;
  prompt: string;
  status: string;
  created_at: string;
  updated_at?: string;
  error?: string;
  runtime?: string;
};

export type ProviderStatus = {
  name: string;
  display_name: string;
  model: string;
  enabled: boolean;
  default: boolean;
  key_status: string;
};

export type ToolStatus = {
  name: string;
  description: string;
  category: string;
  requires_approval: boolean;
  policy?: Record<string, unknown>;
  connector_origin?: Record<string, unknown>;
};

export type TickerSummary = {
  inst_id: string;
  last: string;
  volume_ccy_24h: string;
  change_utc0_pct: string;
};

export type PaperPosition = {
  inst_id: string;
  side: string;
  quantity: string;
  entry_price: string;
  mark_price: string;
  notional: string;
  unrealized_pnl: string;
};

export type PaperFill = {
  inst_id: string;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  created_at?: string;
};

export type StrategyResearchSummary = {
  id: string;
  prompt: string;
  strategy_key: string;
  title: string;
  report_markdown: string;
  spec_json: Record<string, unknown>;
  created_at: string;
};

export type MissionProjection = {
  mission_id: string;
  objective: string;
  status: string;
  active_plan_version?: number;
  current_step_id?: string;
  usage?: { tokens?: number; tool_calls?: number; step_attempts?: number; duration_ms?: number };
  budget?: { max_tokens?: number; max_tool_calls?: number; max_attempts_per_step?: number };
  plans?: Array<{ version: number; steps?: Array<{ step_id: string; title: string; capability_id: string }> }>;
  attempts?: Array<{ step_id: string; status: string; observation?: { summary?: string } }>;
  artifact_refs?: string[];
  unknowns?: string[];
};

export type MissionEvent = {
  sequence: number;
  event_type: string;
  actor?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

export type BacktestSummary = {
  id: string;
  research_id: string;
  strategy_key: string;
  status: string;
  metrics: {
    start_cash: string;
    end_value: string;
    total_return_pct: string;
    max_drawdown_pct: string;
    trade_count: number;
  };
  report_markdown: string;
  report_json: Record<string, unknown>;
  created_at: string;
};

export type StrategyExperimentSummary = {
  id: string;
  prompt: string;
  status: string;
  research_id: string;
  backtest_id: string;
  report_markdown: string;
  report_json: Record<string, unknown>;
  created_at: string;
};

export type LiveOrderIntent = {
  id: string;
  environment: string;
  status: string;
  inst_id: string;
  side: string;
  order_type: string;
  size: string;
  price: string | null;
  reason: string;
  decision_reason: string;
  risk_status?: string;
  exchange_order_id?: string;
  created_at: string;
};

export type MemoryItem = {
  id: string;
  kind: string;
  content: string;
  source_run_id: string;
  source_tool: string;
  tags?: string[];
  usage_count?: number;
  importance?: string;
  confidence?: string;
  last_used_at?: string | null;
  created_at: string;
};

export type CognitiveMemoryCounts = {
  episodic_count: number;
  semantic_count: number;
  active_semantic_count: number;
  hypothesis_count: number;
};

export type SemanticCognitiveItem = {
  id: string;
  tier: "semantic";
  kind: string;
  status: string;
  claim: string;
  confidence: string;
  regimes: string[];
  symbols: string[];
  timeframe: string;
  distillation_version: number;
  derived_episode_count: number;
  created_at: string;
};

export type EpisodicCognitiveItem = {
  id: string;
  tier: "episodic";
  kind: string;
  mission_id: string;
  experiment_id: string;
  symbols: string[];
  timeframe: string;
  market_regime: string;
  raw_evidence_ref: string;
  summary: string;
  created_at: string;
};

export type CognitiveMemoryItem = SemanticCognitiveItem | EpisodicCognitiveItem;

export type MemoryPayload = {
  items: MemoryItem[];
  cognitive?: CognitiveMemoryCounts;
  cognitive_items?: CognitiveMemoryItem[];
};

export type MemoryAssertion = {
  id: string;
  claim: string;
  status: string;
  usable: boolean;
  source_evidence_ids?: string[];
  confidence?: string;
};

export type SkillProposal = {
  id: string;
  skill_key: string;
  status: string;
  definition_hash: string;
  diff?: string;
};

export type SkillRelease = {
  id: string;
  skill_key: string;
  version: number;
  status: string;
};

export type RagHit = {
  source_path: string;
  title: string;
  chunk_index: number;
  score: number;
  content_preview: string;
};

export type EvalStatus = {
  status: string;
  case_count: number;
  legacy_case_count?: number;
  research_os_case_count?: number;
  cases: Array<{ name: string; status: string; expectation?: string }>;
  mode: string;
  research_os?: {
    status?: string;
    suite_version?: string;
    case_count?: number;
  };
  quality?: {
    metric_contract?: string;
    status?: string;
    suite_version?: string;
    provider_baseline?: string;
    cohorts?: Record<string, number>;
    failure_categories?: Record<string, number>;
  };
};

export type StrategyEvidence = {
  memory_id?: string;
  experiment_id?: string;
  research_id?: string;
  backtest_id?: string;
  bitpro_result_id?: string;
  variant_id?: string;
  passed?: boolean;
  total_return_pct?: string;
  max_drawdown_pct?: string;
  trade_count?: number;
  score?: string;
  data?: Record<string, unknown>;
  gate_results?: Record<string, unknown>;
  failure_reasons?: string[];
  next_experiment?: string;
  created_at?: string;
};

export type StrategyLibraryItem = {
  strategy_key: string;
  evidence_count: number;
  passed_count: number;
  failed_count: number;
  best?: StrategyEvidence;
  latest?: StrategyEvidence;
  variants?: Array<{ variant_id: string; evidence_count: number; passed_count: number }>;
  failure_reasons?: string[];
  next_experiments?: string[];
  source_memory_ids?: string[];
};

export type StrategyLibraryPayload = {
  source: string;
  memory_count: number;
  items: StrategyLibraryItem[];
};

export type MonitorAlert = {
  id?: string;
  severity?: string;
  code?: string;
  title?: string;
  message?: string;
  source_id?: string;
  created_at?: string;
  threshold?: string;
  source_refs?: string[];
};

export type EvolutionAlert = {
  id: string;
  code: string;
  severity: string;
  strategy_id?: number | string | null;
  message: string;
  status: string;
  delivery_result?: string | null;
  delivered_at?: string | null;
  created_at: string;
  delivery_verified?: boolean;
};

export type RuntimeErrorRecord = {
  error_id: string;
  component: string;
  exception_type: string;
  message: string;
  mission_id?: string | null;
  occurrences: number;
  frames?: string[];
  recent_messages?: string[];
  context?: Record<string, unknown>;
  first_seen_at: string;
  last_seen_at: string;
};

export type WorkerComponentHealth = {
  last_ok_age_seconds: number | null;
  last_error_age_seconds: number | null;
  last_error_type: string | null;
  consecutive_failures: number;
  failures_total: number;
  restarts_total: number;
};

export type WorkerStallView = {
  seconds: number;
  age_seconds: number | null;
  running: string[];
  cause?: string;
  [key: string]: unknown;
};

export type WorkerInstanceHealth = {
  worker_id: string;
  stale: boolean;
  heartbeat_age_seconds: number;
  uptime_seconds: number;
  build_sha?: string | null;
  event_loop_lag_max_seconds: number | null;
  stalls_total: number;
  stall_causes: Record<string, number>;
  last_stall: WorkerStallView | null;
  process: Record<string, unknown> | null;
  failing_components: string[];
  components: Record<string, WorkerComponentHealth>;
};

export type HealthzPayload = {
  status: string;
  timestamp: string;
  uptime_seconds: number;
  total_latency_ms: number;
  database: {
    status: string;
    latency_ms: number;
  };
  build?: Record<string, unknown>;
  adapters?: Record<string, Record<string, unknown>>;
  workers?: {
    status: "alive" | "stale" | "unknown" | string;
    reason?: string;
    failing_components?: string[];
    instances?: WorkerInstanceHealth[];
  };
  paper_session?: string;
  security?: {
    active_tokens?: number;
    expiring_soon_tokens?: number;
  };
};

export type EvolutionSourceBudget = {
  target_id: string;
  source_strategy_id: string | number;
  source_instance_id: string;
  last_admitted_at?: string;
  busy: boolean;
  in_research: boolean;
  observing_slots: number;
  slot_limit: number;
  slots_open: number;
  active_slot_variants: Array<Record<string, unknown>>;
  last_state?: string;
  cooldown_at?: string;
  cooldown_hours?: number;
  reason?: string | null;
  next_run_at?: string | null;
  last_provider?: string;
  failure_streak?: number;
  failure_reason?: string | null;
};

export type EvolutionCycleView = {
  id?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  summary?: string;
  diagnostics?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type EvolutionStatusPayload = {
  config: {
    enabled: boolean;
    target_id?: string;
    launch_enabled?: boolean;
    launch_days?: number;
    exploration_provider?: string;
    exploration_cooldown_hours?: number;
    paper_admission?: string;
    paper_review_mode?: string;
    max_research_per_day?: number;
    max_active_research?: number;
    max_candidates?: number;
    [key: string]: unknown;
  };
  budget: {
    period?: string;
    period_used?: number;
    period_limit?: number;
    active?: number;
    total_used?: number;
    reason?: string | null;
    next_run_at?: string | null;
    sources?: Record<string, EvolutionSourceBudget>;
    [key: string]: unknown;
  };
  revision: number;
  cycles?: EvolutionCycleView[];
  continuations?: Array<Record<string, unknown>>;
  forward_outcomes?: Record<string, unknown>;
};

export type RaceJudgeRecord = {
  parent_strategy_id: string | number;
  challenger_strategy_id: string | number;
  target_id?: string;
  generation?: number;
  parent_name?: string;
  challenger_name?: string;
  state: string;
  eligible: boolean;
  reason?: string;
  observed_hours?: number | null;
  target_hours?: number;
  parent_net_return_pct?: number | null;
  challenger_net_return_pct?: number | null;
  excess_return_pct?: number | null;
  sign_test_p?: number | null;
  positive_days?: number;
  paired_non_tie_days?: number;
  slot_no?: number | null;
  gate_alpha?: number | null;
  cancellation_kind?: string | null;
  cancellation_reason?: string | null;
  updated_at?: string;
};

export type EvidenceSelection = {
  title: string;
  rows: Array<{ label: string; value: string }>;
};

export type RouteMetric = {
  label: string;
  value: string;
  tone: "signal" | "brass" | "violet" | "danger";
};

export type ReportBlock = {
  block_type?: string;
  title?: string;
  severity?: string;
  notes?: unknown;
  metrics?: unknown;
  rows?: unknown;
  missing?: unknown;
  source_refs?: unknown;
};

export type MissionsSummary = {
  total_count: number;
  active_count: number;
  completed_count: number;
  failed_count: number;
  threads_count: number;
};

export type HarnessOverview = {
  generated_at: string;
  headless_mode?: boolean;
  missions_summary?: MissionsSummary;
  providers: ProviderStatus[];
  tools: ToolStatus[];
  connectors?: Array<Record<string, unknown>>;
  market: {
    ticker_count: number;
    latest_ticker_at: string | null;
    latest_update_age_seconds: number | null;
    top_movers: TickerSummary[];
  };
  agent_runs: {
    total_count: number;
    recent: RunSummary[];
  };
  rag: {
    document_count: number;
    chunk_count: number;
  };
  memory: {
    active_count: number;
    total_count: number;
    latest_created_at: string | null;
    cognitive?: CognitiveMemoryCounts;
  };
  trace: {
    total_count: number;
    recent_events: TraceEvent[];
  };
  observability?: {
    window_size: number;
    completed_runs: number;
    success_rate: number;
    model_requests: number;
    total_tokens: number;
    usage_reported_runs: number;
    p50_duration_ms: number;
    p95_duration_ms: number;
    private_reasoning_stored: boolean;
  };
  paper: {
    session: {
      id: string;
      status: string;
      cash: string;
      equity: string;
      realized_pnl: string;
    };
    positions: PaperPosition[];
    recent_fills: PaperFill[];
    recent_events: Array<Record<string, unknown>>;
  };
  strategy_lab: {
    latest_research: StrategyResearchSummary | null;
    latest_backtest: BacktestSummary | null;
    latest_experiment: StrategyExperimentSummary | null;
  };
  live_orders: {
    total_count: number;
    pending_approval_count: number;
    recent: LiveOrderIntent[];
  };
  bitpro?: {
    adapter: string;
    configured: boolean;
    api_base: string;
    auth_header: string;
    token_configured: boolean;
    token_source?: string;
    remote_mcp?: {
      transport?: string;
      path_default?: string;
      auth_header_default?: string;
      token_env?: string;
      token_status_path?: string;
      token_generate_path?: string;
    };
    agent_auth?: {
      auth_header_default?: string;
      static_token_env?: string;
      token_management?: {
        settings_routes?: Record<string, string>;
        plaintext_returned_once?: boolean;
        default_tool_groups?: string[];
      };
      scope_classes?: Record<
        string,
        {
          label?: string;
          tool_group?: string;
          description?: string;
        }
      >;
      idempotency?: {
        required_tools?: string[];
      };
    };
    tool_groups?: Record<string, string[]>;
    live_write_enabled: boolean;
    live_write_scope?: string;
    live_write_note?: string;
    tools: string[];
    live_probe?: {
      reachable: boolean;
      authenticated: boolean;
      status: string;
      latency_ms?: number | null;
      error?: string | null;
      hint?: string | null;
    } | null;
  };
  evals: EvalStatus;
};

/**
 * "unknown" until the server refuses a privileged call (401/403), then "readonly". The console
 * deliberately never probes the session or offers a login form (privileged actions use the CLI's
 * `ht /login`, see docs/deployment.md), so it only learns it is read-only when an action is refused.
 */
export type AccessMode = "unknown" | "readonly";
