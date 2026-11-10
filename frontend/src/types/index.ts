// Shared shapes of the operator console API payloads and UI state.
// Moved verbatim out of App.tsx; nothing here changes behaviour.

export type Language = "zh" | "en";
export type NavSection =
  | "harness"
  | "missions"
  | "strategy"
  | "portfolio"
  | "alerts"
  | "runs"
  | "quality"
  | "memory"
  | "rag";

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
  updated_at: string;
  error: string;
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

export type MissionEvent = { sequence: number; event_type: string; actor?: string; payload?: Record<string, unknown>; created_at?: string };

export type StrategyCardProjection = {
  card_id: string;
  strategy_key: string;
  lifecycle_status?: string;
  completeness_score?: string;
  missing_fields?: string[];
};

export type ResearchFunnel = {
  denominator: number;
  denominator_unit: string;
  stages: Record<string, number>;
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

export type PortfolioRecommendation = {
  recommendation_id: string;
  action: string;
  strategy_card_id: string;
  reason: string;
  requires_human_review: boolean;
  allocation_change_allowed: boolean;
  trading_mutation_allowed: boolean;
};

export type PortfolioAssessment = {
  id: string;
  status: string;
  policy_version: string;
  valid_until: string;
  strategies: Array<Record<string, unknown>>;
  pairwise: Array<Record<string, unknown>>;
  unknowns: string[];
  recommendations: PortfolioRecommendation[];
};

export type PortfolioObservationWindow = {
  id: string;
  status: string;
  horizon_days: number;
  bucket_minutes: number;
  quality: {
    denominator: number;
    available_count: number;
    coverage_ratio: string;
    gaps: string[];
  };
  strategies: Array<Record<string, unknown>>;
  pairwise: Array<Record<string, unknown>>;
  raw_series_persisted: boolean;
};

export type PaperCohort = {
  id: string;
  status: string;
  version_number: number;
  intake_count: number;
  comparable_count: number;
  proposal_count: number;
  groups: Array<Record<string, unknown>>;
  execution_authorized: boolean;
};

export type PaperIncubationMandate = {
  id: string;
  status: string;
  kill_switch: boolean;
  policy_hash: string;
  fixed_denominator: number;
  members: Array<{
    id: string;
    status: string;
    candidate_id: string;
    validation_id: string;
    rejection_reasons: string[];
  }>;
  actions: Array<{
    id: string;
    action: string;
    status: string;
    reason: string;
    outcome_link: string;
  }>;
  mutation_boundary: {
    paper_only: boolean;
    testnet_writes: boolean;
    live_writes: boolean;
    real_order_writes: boolean;
    capital_transfer_writes: boolean;
  };
};

export type ShadowPortfolio = {
  id: string;
  status: string;
  version_number: number;
  intake_count: number;
  eligible_count: number;
  scenario_count: number;
  scenarios: Array<{ scenario_id: string; template: string }>;
  hypothetical: boolean;
  execution_authorized: boolean;
  capital_authorized: boolean;
};

export type MarketRegimeSnapshotV2 = {
  id: string;
  status: string;
  as_of: string;
  confidence: string;
  probabilities: Record<string, string>;
  unknowns: string[];
  execution_authorized: boolean;
};

export type RegimeShadowTargetV2 = {
  id: string;
  status: string;
  version_number: number;
  eligible_count: number;
  intake_denominator: number;
  selected_template: string;
  estimated_turnover: string;
  estimated_cost_bps: string;
  target_weights: Array<{ card_id: string; weight: string }>;
  eligibility: Array<{
    card_id: string;
    status: string;
    reasons: string[];
  }>;
  unknowns: string[];
  execution_authorized: boolean;
  capital_authorized: boolean;
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

export type HarnessOverview = {
  generated_at: string;
  providers: ProviderStatus[];
  tools: ToolStatus[];
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
  };
  evals: EvalStatus;
};

/**
 * "unknown" until the server refuses a privileged call (401/403), then "readonly". The console
 * deliberately never probes the session or offers a login form (privileged actions use the CLI's
 * `ht /login`, see docs/deployment.md), so it only learns it is read-only when an action is refused.
 */
export type AccessMode = "unknown" | "readonly";
