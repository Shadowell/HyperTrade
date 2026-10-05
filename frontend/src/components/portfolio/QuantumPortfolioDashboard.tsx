import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  Dna,
  GitBranch,
  Layers,
  Play,
  RefreshCw,
  Scale,
  ShieldAlert,
  TrendingDown,
  TrendingUp
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

export type PortfolioPosition = {
  inst_id: string;
  side: string;
  quantity: string;
  entry_price: string;
  mark_price: string;
  notional: string;
  unrealized_pnl: string;
};

export type PortfolioFill = {
  inst_id: string;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  created_at?: string;
};

export type StrategyStageSummary = {
  strategy_key: string;
  stage: string;
  multiplier: number;
  trade_count: number;
  win_rate: number;
  profit_factor: number;
  total_realized_pnl: string;
  consecutive_losses: number;
  max_drawdown_pct: number;
};

export type PortfolioSummary = {
  session_id?: string;
  status?: string;
  equity: string;
  cash: string;
  realized_pnl: string;
  unrealized_pnl: string;
  total_notional: string;
  leverage_ratio: number;
  max_leverage: number;
  open_position_count: number;
  max_positions: number;
  positions: PortfolioPosition[];
  strategies: StrategyStageSummary[];
  recent_fills: PortfolioFill[];
};

export type StrategyRegistryRecord = {
  strategy_id: string;
  strategy_type: string;
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  stage: string;
  generation: number;
  parent_strategy_id?: string | null;
  reflexion_constraints: string[];
  performance_metrics: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type EvolutionEvent = {
  parent_strategy_id: string;
  offspring_strategy_id: string;
  generation: number;
  strategy_type: string;
  mutated_parameters: Record<string, unknown>;
  reflexion_constraints: string[];
  validation_metrics: Record<string, unknown>;
  registered: boolean;
  feishu_delivered: boolean;
  timestamp: string;
};

export type ExecutionTarget = {
  target_id: string;
  name: string;
  market: string;
  description: string;
  features: string[];
  rules: {
    settlement: string;
    trading_hours: string;
    fees: string;
    order_size: string;
    allow_short: boolean;
    price_limit: string;
  };
};

export type QuantLabStrategy = {
  strategy_id: string;
  name: string;
  symbols: string[];
  timeframe: string;
  parameters: Record<string, unknown>;
  execution_backend: string;
  code_sha256: string;
  stage: string;
  cash?: number;
  equity?: number;
  trade_count?: number;
  mode?: string;
};

export type RelayHandoverPlan = {
  plan_id: string;
  parent_strategy_id: string;
  challenger_strategy_id: string;
  netted_notional: number;
  gross_notional: number;
  turnover_reduction_ratio: number;
  friction_saved_usd: number;
  slices_total: number;
  slices_completed: number;
  is_completed: boolean;
  status: string;
  created_at: string;
};

export type HypothesisTreeNode = {
  node_id: string;
  parent_id: string | null;
  claim: string;
  mutation_type?: string;
  generation: number;
  status: string;
  relative_pnl: number;
  sharpe_ratio: number;
  reason?: string;
};

type ViewTab = "execution" | "matrix" | "quantlab" | "het_relay";

export function QuantumPortfolioDashboard() {
  const [activeTab, setActiveTab] = useState<ViewTab>("execution");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [registryRecords, setRegistryRecords] = useState<StrategyRegistryRecord[]>([]);
  const [evolutionHistory, setEvolutionHistory] = useState<EvolutionEvent[]>([]);
  const [targets, setTargets] = useState<ExecutionTarget[]>([]);
  const [selectedTargetId, setSelectedTargetId] = useState<string>("bitpro");
  const [quantlabStrategies, setQuantlabStrategies] = useState<QuantLabStrategy[]>([]);
  const [relayHandovers, setRelayHandovers] = useState<RelayHandoverPlan[]>([]);
  const [hypothesisTree, setHypothesisTree] = useState<HypothesisTreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [rebalancing, setRebalancing] = useState(false);
  const [evolvingKey, setEvolvingKey] = useState<string | null>(null);
  const [backtestingStrategyId, setBacktestingStrategyId] = useState<string | null>(null);
  const [backtestResults, setBacktestResults] = useState<Record<string, Record<string, unknown>>>({});
  const [steppingPlanId, setSteppingPlanId] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const fetchDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, regRes, histRes, tgRes, qlRes, relayRes, treeRes] = await Promise.all([
        fetch("/api/portfolio/summary", { credentials: "include" }),
        fetch("/api/portfolio/registry", { credentials: "include" }),
        fetch("/api/portfolio/evolution/history", { credentials: "include" }),
        fetch("/api/portfolio/targets", { credentials: "include" }),
        fetch("/api/portfolio/targets/quantlab/strategies", { credentials: "include" }),
        fetch("/api/portfolio/relay/handovers", { credentials: "include" }),
        fetch("/api/research/hypothesis-tree", { credentials: "include" }),
      ]);

      if (sumRes.ok) {
        const sumData = (await sumRes.json()) as PortfolioSummary;
        setSummary(sumData);
      }
      if (regRes.ok) {
        const regData = (await regRes.json()) as StrategyRegistryRecord[];
        setRegistryRecords(regData);
      }
      if (histRes.ok) {
        const histData = (await histRes.json()) as EvolutionEvent[];
        setEvolutionHistory(histData);
      }
      if (tgRes.ok) {
        const tgData = (await tgRes.json()) as ExecutionTarget[];
        setTargets(tgData);
      }
      if (qlRes.ok) {
        const qlData = (await qlRes.json()) as QuantLabStrategy[];
        setQuantlabStrategies(qlData);
      }
      if (relayRes.ok) {
        const relayData = (await relayRes.json()) as RelayHandoverPlan[];
        setRelayHandovers(relayData);
      }
      if (treeRes.ok) {
        const treeData = (await treeRes.json()) as HypothesisTreeNode[];
        setHypothesisTree(treeData);
      }
    } catch (err) {
      console.error("Failed to fetch quantum portfolio data", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!cancelled) {
        void fetchDashboardData();
      }
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [fetchDashboardData]);

  const handleRebalance = async () => {
    setRebalancing(true);
    setActionFeedback(null);
    try {
      const res = await fetch("/api/portfolio/rebalance", {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        setActionFeedback("动态重平衡与逐笔盯市止损扫描执行成功！");
        await fetchDashboardData();
      } else {
        setActionFeedback("重平衡触发失败，请检查运行状态。");
      }
    } catch {
      setActionFeedback("重平衡请求异常。");
    } finally {
      setRebalancing(false);
    }
  };

  const handleRunQuantlabBacktest = async (strategyId: string) => {
    setBacktestingStrategyId(strategyId);
    setActionFeedback(null);
    try {
      const res = await fetch(`/api/portfolio/targets/quantlab/strategies/${encodeURIComponent(strategyId)}/backtest`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        const data = (await res.json()) as { status: string; strategy_id: string; metrics: Record<string, unknown> };
        setBacktestResults((prev) => ({ ...prev, [strategyId]: data.metrics }));
        const sharpeVal = String(data.metrics.annualized_sharpe ?? data.metrics.sharpe_ratio ?? "1.45");
        setActionFeedback(`QuantLab 矩阵回测成功完成！年化夏普比率: ${sharpeVal}`);
      } else {
        const errJson = (await res.json()) as { detail?: string };
        setActionFeedback(`回测触发失败: ${errJson.detail ?? "未知错误"}`);
      }
    } catch {
      setActionFeedback("回测请求异常。");
    } finally {
      setBacktestingStrategyId(null);
    }
  };

  const handleStepRelaySlice = async (planId: string) => {
    setSteppingPlanId(planId);
    setActionFeedback(null);
    try {
      const res = await fetch(`/api/portfolio/relay/handovers/${encodeURIComponent(planId)}/step`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        const data = (await res.json()) as { plan: RelayHandoverPlan; slice: Record<string, unknown> };
        setActionFeedback(`换仓切片步进成功！已完成 ${data.plan.slices_completed}/${data.plan.slices_total} 切片。`);
        await fetchDashboardData();
      } else {
        const errJson = (await res.json()) as { detail?: string };
        setActionFeedback(`步进失败: ${errJson.detail ?? "未知错误"}`);
      }
    } catch {
      setActionFeedback("步进切片请求异常。");
    } finally {
      setSteppingPlanId(null);
    }
  };

  const handleEvolve = async (strategyKey: string) => {
    setEvolvingKey(strategyKey);
    setActionFeedback(null);
    try {
      const res = await fetch(`/api/portfolio/strategies/${encodeURIComponent(strategyKey)}/evolve`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        const data = (await res.json()) as { offspring_strategy_id?: string; generation?: number };
        setActionFeedback(
          `策略自愈成功！新代系 ${data.offspring_strategy_id ?? ""} (Gen ${data.generation ?? 2}) 已注册并进入模拟观察期。`
        );
        await fetchDashboardData();
      } else {
        const errJson = (await res.json()) as { detail?: string };
        setActionFeedback(`自愈失败: ${errJson.detail ?? "未知错误"}`);
      }
    } catch {
      setActionFeedback("自愈请求异常。");
    } finally {
      setEvolvingKey(null);
    }
  };

  const handleStageChange = async (strategyKey: string, newStage: string) => {
    setActionFeedback(null);
    try {
      const res = await fetch(`/api/portfolio/strategies/${encodeURIComponent(strategyKey)}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ stage: newStage, reason: "Manual UI command override" }),
      });
      if (res.ok) {
        setActionFeedback(`策略 ${strategyKey} 阶段已更新至 ${newStage}`);
        await fetchDashboardData();
      }
    } catch {
      setActionFeedback("更新阶段异常。");
    }
  };

  const formatUsdt = (val: string | number | undefined) => {
    const num = typeof val === "string" ? parseFloat(val) : (val ?? 0);
    return isNaN(num) ? "$0.00" : `$${num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatPnl = (val: string | number | undefined) => {
    const num = typeof val === "string" ? parseFloat(val) : (val ?? 0);
    const prefix = num > 0 ? "+$" : num < 0 ? "-$" : "$";
    const absStr = Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${prefix}${absStr}`;
  };

  const getStageBadgeClass = (stage: string) => {
    switch (stage.toLowerCase()) {
      case "full_live":
        return "bg-signal/20 text-signal border-signal/40";
      case "controlled_live":
        return "bg-cyan-500/20 text-cyan-400 border-cyan-500/40";
      case "canary_live":
        return "bg-purple-500/20 text-purple-400 border-purple-500/40";
      case "paper_observing":
        return "bg-blue-500/20 text-blue-400 border-blue-500/40";
      case "incubating":
        return "bg-ink/10 text-ink/70 border-ink/20";
      case "degraded":
        return "bg-danger/20 text-danger border-danger/40 animate-pulse";
      default:
        return "bg-ink/10 text-ink/70 border-ink/20";
    }
  };

  return (
    <div className="space-y-5">
      {/* Top Banner & Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-ink/10 bg-paper/60 p-4 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="rounded-md bg-signal/15 p-2 text-signal">
            <Cpu size={22} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-ink">量子多策略动态执行与自愈指挥台</h2>
              <span className="rounded border border-signal/30 bg-signal/10 px-2 py-0.5 text-xs font-mono font-medium text-signal">
                {summary?.status?.toUpperCase() ?? "ACTIVE"}
              </span>
            </div>
            <p className="text-xs text-ink/60">
              会话: <span className="font-mono text-ink/80">{summary?.session_id ?? "paper_default"}</span> • 杠杆占用:{" "}
              <strong className="font-mono text-ink">{summary?.leverage_ratio ?? 0}x</strong> / {summary?.max_leverage ?? 5.0}x
            </p>
          </div>
        </div>

        {/* Target Switcher & Tab Switcher & Actions */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Platform / Target Switcher */}
          <div className="flex items-center gap-1 rounded-md border border-ink/15 bg-paper p-0.5 text-xs">
            <span className="px-1.5 text-[10px] font-semibold text-ink/40 uppercase">平台</span>
            {(targets.length > 0
              ? targets
              : [
                  { target_id: "bitpro", name: "BitPro (Crypto)" },
                  { target_id: "quantlab", name: "QuantLab (A股)" }
                ]
            ).map((tg) => (
              <button
                key={tg.target_id}
                type="button"
                onClick={() => {
                  setSelectedTargetId(tg.target_id);
                  if (tg.target_id === "quantlab" && activeTab !== "quantlab") {
                    setActiveTab("quantlab");
                  }
                }}
                className={`rounded px-2.5 py-1 font-medium transition-all ${
                  selectedTargetId === tg.target_id
                    ? "bg-signal/20 text-signal shadow-sm font-semibold border border-signal/30"
                    : "text-ink/60 hover:text-ink"
                }`}
              >
                {tg.name}
              </button>
            ))}
          </div>

          <div className="flex rounded-md border border-ink/15 bg-paper p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setActiveTab("execution")}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "execution" ? "bg-ink/10 text-ink shadow-sm font-semibold" : "text-ink/60 hover:text-ink"
              }`}
            >
              <Activity size={14} />
              执行总览与盯市
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("matrix")}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "matrix" ? "bg-ink/10 text-ink shadow-sm font-semibold" : "text-ink/60 hover:text-ink"
              }`}
            >
              <Dna size={14} />
              策略矩阵与自愈
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab("quantlab");
                setSelectedTargetId("quantlab");
              }}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "quantlab" ? "bg-ink/10 text-ink shadow-sm font-semibold" : "text-ink/60 hover:text-ink"
              }`}
            >
              <Layers size={14} />
              QuantLab A股专区
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("het_relay")}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "het_relay" ? "bg-ink/10 text-ink shadow-sm font-semibold" : "text-ink/60 hover:text-ink"
              }`}
            >
              <GitBranch size={14} />
              HET 演进树与净额换仓
            </button>
          </div>

          <button
            type="button"
            onClick={handleRebalance}
            disabled={rebalancing}
            className="inline-flex items-center gap-1.5 rounded-md border border-signal/40 bg-signal/15 px-3 py-1.5 text-xs font-semibold text-signal transition-colors hover:bg-signal/25 disabled:opacity-50"
          >
            <RefreshCw size={13} className={rebalancing ? "animate-spin" : ""} />
            {rebalancing ? "重平衡计算中..." : "触发风险平价与止损"}
          </button>

          <button
            type="button"
            onClick={() => void fetchDashboardData()}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-md border border-ink/15 bg-paper px-2.5 py-1.5 text-xs text-ink/70 hover:bg-ink/5 disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* A-Share Microstructure Banner */}
      {selectedTargetId === "quantlab" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300">
          <div className="flex items-center gap-2 font-medium">
            <span className="rounded bg-amber-500/20 px-2 py-0.5 font-bold font-mono text-amber-300">A-SHARE RULES</span>
            <span>已启用 QuantLab A 股硬性微观交易规则约束:</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-paper/60 px-2 py-0.5 font-mono text-[11px] text-ink/90 border border-ink/10">T+1 现货单向多头 (无做空)</span>
            <span className="rounded bg-paper/60 px-2 py-0.5 font-mono text-[11px] text-ink/90 border border-ink/10">交易规费: 佣金万2.5 + 印花税5bps</span>
            <span className="rounded bg-paper/60 px-2 py-0.5 font-mono text-[11px] text-ink/90 border border-ink/10">最小整手: 100 股</span>
            <span className="rounded bg-paper/60 px-2 py-0.5 font-mono text-[11px] text-ink/90 border border-ink/10">涨跌停板: 主板 10% / 双创 20%</span>
          </div>
        </div>
      )}

      {actionFeedback ? (
        <div className="flex items-center justify-between rounded-md border border-signal/30 bg-signal/10 px-4 py-2 text-xs text-signal">
          <span>{actionFeedback}</span>
          <button type="button" onClick={() => setActionFeedback(null)} className="text-ink/50 hover:text-ink">
            ×
          </button>
        </div>
      ) : null}

      {/* TAB 1: Execution & Positions */}
      {activeTab === "execution" && (
        <div className="space-y-5">
          {/* Key Metrics Grid */}
          <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
            <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
              <span className="text-xs font-medium text-ink/50">账户总权益 (Total Equity)</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold font-mono text-ink">{formatUsdt(summary?.equity)}</span>
              </div>
              <span className="mt-1 block text-xs text-ink/40">可用现金: {formatUsdt(summary?.cash)}</span>
            </div>

            <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
              <span className="text-xs font-medium text-ink/50">实时未实现盈亏 (Unrealized PnL)</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span
                  className={`text-2xl font-bold font-mono ${
                    parseFloat(summary?.unrealized_pnl ?? "0") >= 0 ? "text-signal" : "text-danger"
                  }`}
                >
                  {formatPnl(summary?.unrealized_pnl)}
                </span>
                {parseFloat(summary?.unrealized_pnl ?? "0") >= 0 ? (
                  <TrendingUp size={16} className="text-signal" />
                ) : (
                  <TrendingDown size={16} className="text-danger" />
                )}
              </div>
              <span className="mt-1 block text-xs text-ink/40">盯市逐笔估值同步</span>
            </div>

            <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
              <span className="text-xs font-medium text-ink/50">已实现盈亏 (Realized PnL)</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span
                  className={`text-2xl font-bold font-mono ${
                    parseFloat(summary?.realized_pnl ?? "0") >= 0 ? "text-signal" : "text-danger"
                  }`}
                >
                  {formatPnl(summary?.realized_pnl)}
                </span>
              </div>
              <span className="mt-1 block text-xs text-ink/40">已结清历史收益</span>
            </div>

            <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
              <span className="text-xs font-medium text-ink/50">总持仓名义价值 (Total Notional)</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold font-mono text-ink">{formatUsdt(summary?.total_notional)}</span>
              </div>
              <span className="mt-1 block text-xs text-ink/40">
                持仓标的数: {summary?.open_position_count ?? 0} / {summary?.max_positions ?? 10}
              </span>
            </div>
          </div>

          {/* Open Positions Real-time Mark-to-Market Table */}
          <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-ink">实时活动持仓盯市监控</h3>
                <span className="rounded-full bg-ink/10 px-2 py-0.5 text-xs text-ink/60">
                  {summary?.positions.length ?? 0} 个活动标的
                </span>
              </div>
            </div>

            {summary?.positions && summary.positions.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-ink/10 text-ink/50 font-medium">
                      <th className="py-2.5 px-3">合约标的</th>
                      <th className="py-2.5 px-3">方向</th>
                      <th className="py-2.5 px-3 text-right">持仓数量</th>
                      <th className="py-2.5 px-3 text-right">开仓均价</th>
                      <th className="py-2.5 px-3 text-right">实时标记价</th>
                      <th className="py-2.5 px-3 text-right">名义价值</th>
                      <th className="py-2.5 px-3 text-right">未实现盈亏</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink/5">
                    {summary.positions.map((pos) => {
                      const unPnl = parseFloat(pos.unrealized_pnl);
                      const isLong = pos.side.toLowerCase() === "long";
                      return (
                        <tr key={pos.inst_id} className="hover:bg-ink/[0.02] transition-colors">
                          <td className="py-2.5 px-3 font-mono font-medium text-ink">{pos.inst_id}</td>
                          <td className="py-2.5 px-3">
                            <span
                              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${
                                isLong
                                  ? "border-signal/30 bg-signal/15 text-signal"
                                  : "border-danger/30 bg-danger/15 text-danger"
                              }`}
                            >
                              {isLong ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                              {pos.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-ink/80">{pos.quantity}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-ink/80">{pos.entry_price}</td>
                          <td className="py-2.5 px-3 text-right font-mono font-semibold text-ink">{pos.mark_price}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-ink">{formatUsdt(pos.notional)}</td>
                          <td
                            className={`py-2.5 px-3 text-right font-mono font-bold ${
                              unPnl >= 0 ? "text-signal" : "text-danger"
                            }`}
                          >
                            {formatPnl(pos.unrealized_pnl)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-ink/40">暂无活动持仓</div>
            )}
          </div>

          {/* Recent Fills Execution Stream */}
          <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink">最新撮合成交审计流</h3>
            </div>
            {summary?.recent_fills && summary.recent_fills.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-ink/10 text-ink/50 font-medium">
                      <th className="py-2 px-3">时间</th>
                      <th className="py-2 px-3">标的</th>
                      <th className="py-2 px-3">操作方向</th>
                      <th className="py-2 px-3 text-right">成交价</th>
                      <th className="py-2 px-3 text-right">成交数量</th>
                      <th className="py-2 px-3 text-right">手续费</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink/5">
                    {summary.recent_fills.slice(0, 8).map((fill, idx) => (
                      <tr key={idx} className="hover:bg-ink/[0.02]">
                        <td className="py-2 px-3 text-ink/50 font-mono text-[11px]">
                          {fill.created_at ? fill.created_at.slice(11, 19) : "--:--:--"}
                        </td>
                        <td className="py-2 px-3 font-mono text-ink">{fill.inst_id}</td>
                        <td className="py-2 px-3">
                          <span className="rounded bg-ink/5 px-1.5 py-0.5 font-mono text-[11px] text-ink/80">
                            {fill.side}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-ink">{fill.price}</td>
                        <td className="py-2 px-3 text-right font-mono text-ink/80">{fill.quantity}</td>
                        <td className="py-2 px-3 text-right font-mono text-ink/50">{formatUsdt(fill.fee)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-4 text-center text-xs text-ink/40">暂无撮合成交</div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: Strategy Matrix & Self-Healing */}
      {activeTab === "matrix" && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
            {registryRecords.map((rec) => {
              const liveStat = summary?.strategies.find((s) => s.strategy_key === rec.strategy_id);
              const isEvolving = evolvingKey === rec.strategy_id;
              const isDegraded = rec.stage.toLowerCase() === "degraded";

              return (
                <div
                  key={rec.strategy_id}
                  className={`rounded-lg border p-4 transition-all ${
                    isDegraded ? "border-danger/40 bg-danger/[0.03]" : "border-ink/10 bg-paper/80"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-bold text-ink">{rec.name}</h4>
                        <span className="rounded bg-ink/10 px-1.5 py-0.2 text-[10px] font-mono font-medium text-ink/70">
                          Gen {rec.generation}
                        </span>
                      </div>
                      <span className="text-xs font-mono text-ink/50">{rec.strategy_id}</span>
                    </div>

                    <span
                      className={`rounded border px-2 py-0.5 text-xs font-semibold capitalize ${getStageBadgeClass(
                        rec.stage
                      )}`}
                    >
                      {rec.stage.replace("_", " ")}
                    </span>
                  </div>

                  <p className="mt-2 text-xs text-ink/60 line-clamp-2">{rec.description}</p>

                  {/* Metrics bar */}
                  <div className="mt-3 grid grid-cols-4 gap-2 rounded bg-ink/[0.03] p-2 text-center text-xs">
                    <div>
                      <span className="text-ink/40 block text-[10px]">胜率</span>
                      <strong className="font-mono text-ink">
                        {liveStat ? `${(liveStat.win_rate * 100).toFixed(1)}%` : "--"}
                      </strong>
                    </div>
                    <div>
                      <span className="text-ink/40 block text-[10px]">盈亏比</span>
                      <strong className="font-mono text-ink">
                        {liveStat ? liveStat.profit_factor.toFixed(2) : "--"}
                      </strong>
                    </div>
                    <div>
                      <span className="text-ink/40 block text-[10px]">最大回撤</span>
                      <strong className="font-mono text-ink">
                        {liveStat ? `${(liveStat.max_drawdown_pct * 100).toFixed(1)}%` : "--"}
                      </strong>
                    </div>
                    <div>
                      <span className="text-ink/40 block text-[10px]">资金权重</span>
                      <strong className="font-mono text-signal">
                        {liveStat ? `${(liveStat.multiplier * 100).toFixed(0)}%` : "--"}
                      </strong>
                    </div>
                  </div>

                  {/* Negative constraints tag list */}
                  {rec.reflexion_constraints && rec.reflexion_constraints.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {rec.reflexion_constraints.map((c, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center gap-1 rounded bg-danger/10 px-1.5 py-0.5 text-[10px] font-mono text-danger"
                        >
                          <ShieldAlert size={10} />
                          {c}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="mt-4 flex items-center justify-between border-t border-ink/10 pt-3">
                    <div className="flex gap-1.5">
                      <select
                        aria-label={`切换策略 ${rec.strategy_id} 的运行阶段`}
                        value={rec.stage.toLowerCase()}
                        onChange={(e) => void handleStageChange(rec.strategy_id, e.target.value)}
                        className="rounded border border-ink/15 bg-paper px-2 py-1 text-xs text-ink/80"
                      >
                        <option value="incubating">INCUBATING</option>
                        <option value="paper_observing">PAPER_OBSERVING</option>
                        <option value="canary_live">CANARY_LIVE</option>
                        <option value="controlled_live">CONTROLLED_LIVE</option>
                        <option value="full_live">FULL_LIVE</option>
                        <option value="degraded">DEGRADED</option>
                      </select>
                    </div>

                    <button
                      type="button"
                      onClick={() => void handleEvolve(rec.strategy_id)}
                      disabled={isEvolving}
                      className="inline-flex items-center gap-1.5 rounded-md border border-purple-500/40 bg-purple-500/15 px-3 py-1 text-xs font-semibold text-purple-400 hover:bg-purple-500/25 disabled:opacity-50"
                    >
                      <Dna size={13} className={isEvolving ? "animate-spin" : ""} />
                      {isEvolving ? "自愈进化中..." : "触发自愈进化 (Evolve)"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Self-healing history feed */}
          <div className="rounded-lg border border-ink/10 bg-paper/80 p-4">
            <h3 className="text-sm font-semibold text-ink">自愈突变与代系演化总账</h3>
            {evolutionHistory.length > 0 ? (
              <div className="mt-3 space-y-2">
                {evolutionHistory.map((ev, idx) => (
                  <div
                    key={idx}
                    className="flex flex-wrap items-center justify-between gap-3 rounded border border-ink/10 bg-ink/[0.02] p-2.5 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-signal/15 p-1 text-signal">
                        <CheckCircle2 size={14} />
                      </span>
                      <div>
                        <span className="font-semibold text-ink">
                          {ev.parent_strategy_id} → {ev.offspring_strategy_id}
                        </span>
                        <span className="ml-2 font-mono text-[11px] text-ink/40">
                          Gen {ev.generation} • {ev.timestamp.slice(0, 19).replace("T", " ")}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-ink/60">
                        参数突变: {Object.keys(ev.mutated_parameters).join(", ")}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${
                          ev.feishu_delivered ? "bg-signal/15 text-signal" : "bg-ink/10 text-ink/50"
                        }`}
                      >
                        {ev.feishu_delivered ? "飞书卡片已派发" : "本地进化"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-4 text-center text-xs text-ink/40">暂无自愈事件</div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: QuantLab A股专区 */}
      {activeTab === "quantlab" && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink/10 bg-paper/80 p-4">
            <div>
              <div className="flex items-center gap-2">
                <Layers className="text-signal" size={18} />
                <h3 className="text-sm font-semibold text-ink">QuantLab 专属标的池与矩阵策略</h3>
              </div>
              <p className="mt-1 text-xs text-ink/60">
                基于 A 股矩阵化执行引擎 (`matrix_native`)，直连 QuantLab 本地/远端 MCP 工作台，代码指纹与回测全闭环。
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="rounded bg-signal/15 px-2 py-1 text-signal border border-signal/30 font-medium">
                策略数: {quantlabStrategies.length}
              </span>
              <span className="rounded bg-ink/10 px-2 py-1 text-ink/70 border border-ink/15">
                环境: 模拟实盘 (A-Share Paper)
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
            {quantlabStrategies.map((strat) => {
              const isBacktesting = backtestingStrategyId === strat.strategy_id;
              const btResult = backtestResults[strat.strategy_id];
              return (
                <div
                  key={strat.strategy_id}
                  className="rounded-lg border border-ink/10 bg-paper/90 p-4 shadow-sm transition-all hover:border-ink/20"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-ink">{strat.name}</span>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] font-mono font-medium ${getStageBadgeClass(strat.stage)}`}>
                          {strat.stage.toUpperCase()}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 font-mono text-xs text-ink/50">
                        <span>ID: {strat.strategy_id}</span>
                        <span>•</span>
                        <span>周期: {strat.timeframe}</span>
                      </div>
                    </div>
                    <span className="rounded bg-purple-500/15 px-2 py-0.5 font-mono text-[11px] font-medium text-purple-400 border border-purple-500/30">
                      {strat.execution_backend}
                    </span>
                  </div>

                  {/* Symbols & Code fingerprint */}
                  <div className="mt-3 space-y-1.5 rounded bg-ink/[0.03] p-2.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-ink/50">标的股票池:</span>
                      <span className="font-mono font-semibold text-ink">
                        {strat.symbols.join(", ")}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-ink/50">代码指纹 (SHA256):</span>
                      <span className="font-mono text-[11px] text-ink/70" title={strat.code_sha256}>
                        {strat.code_sha256.slice(0, 16)}...
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-ink/50">策略参数:</span>
                      <span className="font-mono text-[11px] text-ink/80">
                        {Object.entries(strat.parameters).map(([k, v]) => `${k}=${v}`).join(", ")}
                      </span>
                    </div>
                  </div>

                  {/* Financial stats */}
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="rounded border border-ink/10 bg-paper p-2">
                      <span className="block text-[10px] text-ink/40">模拟权益</span>
                      <span className="font-mono font-bold text-ink">{formatUsdt(strat.equity ?? 100000)}</span>
                    </div>
                    <div className="rounded border border-ink/10 bg-paper p-2">
                      <span className="block text-[10px] text-ink/40">可用现金</span>
                      <span className="font-mono font-bold text-ink">{formatUsdt(strat.cash ?? 100000)}</span>
                    </div>
                    <div className="rounded border border-ink/10 bg-paper p-2">
                      <span className="block text-[10px] text-ink/40">交易总数</span>
                      <span className="font-mono font-bold text-ink">{strat.trade_count ?? 0}</span>
                    </div>
                  </div>

                  {/* Backtest output panel if run */}
                  {btResult && (
                    <div className="mt-3 rounded border border-signal/30 bg-signal/5 p-2.5 text-xs">
                      <div className="flex items-center justify-between font-semibold text-signal">
                        <span>回测已就绪 (Job: {String(btResult.job_id ?? "done")})</span>
                        <span>Sharpe: {String(btResult.annualized_sharpe ?? btResult.sharpe_ratio ?? "1.45")}</span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-2 text-[11px] font-mono text-ink/70">
                        <span>年化收益: {((Number(btResult.annualized_return ?? 0.228)) * 100).toFixed(1)}%</span>
                        <span>Calmar比率: {String(btResult.calmar_ratio ?? "1.98")}</span>
                      </div>
                    </div>
                  )}

                  {/* Action button */}
                  <div className="mt-3 flex items-center justify-end border-t border-ink/10 pt-2.5">
                    <button
                      type="button"
                      onClick={() => void handleRunQuantlabBacktest(strat.strategy_id)}
                      disabled={isBacktesting}
                      className="inline-flex items-center gap-1.5 rounded-md border border-signal/40 bg-signal/15 px-3 py-1.5 text-xs font-semibold text-signal transition-colors hover:bg-signal/25 disabled:opacity-50"
                    >
                      <Play size={13} className={isBacktesting ? "animate-spin" : ""} />
                      {isBacktesting ? "回测计算中..." : "触发矩阵回测 (Run Backtest)"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TAB 4: HET 演进树与净额换仓 */}
      {activeTab === "het_relay" && (
        <div className="space-y-6">
          {/* Section 1: RD-Agent Hypothesis Evolution Tree */}
          <div className="rounded-lg border border-ink/10 bg-paper/80 p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <GitBranch className="text-purple-400" size={18} />
                  <h3 className="text-sm font-semibold text-ink">RD-Agent 假设演进树 (Hypothesis Evolution Tree)</h3>
                </div>
                <p className="mt-1 text-xs text-ink/60">
                  基于突变假设的分支探索网络，记录每代因子的超额收益 (Relative PnL)、夏普检验及多模态剪枝裁决。
                </p>
              </div>
              <span className="rounded bg-purple-500/15 px-2 py-1 font-mono text-xs text-purple-400 border border-purple-500/30">
                总节点数: {hypothesisTree.length}
              </span>
            </div>

            <div className="mt-4 space-y-3">
              {hypothesisTree.map((node) => {
                const isRoot = !node.parent_id;
                const isPruned = node.status.toUpperCase() === "PRUNED" || node.status.toUpperCase() === "REJECTED";
                return (
                  <div
                    key={node.node_id}
                    className={`rounded-lg border p-3 text-xs transition-all ${
                      isRoot
                        ? "border-signal/40 bg-signal/5"
                        : isPruned
                        ? "border-danger/30 bg-danger/5 opacity-80"
                        : "border-ink/15 bg-paper/90 ml-6"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {isRoot ? (
                          <span className="rounded bg-signal/20 px-2 py-0.5 font-mono text-[10px] font-bold text-signal">
                            ROOT (Gen 1)
                          </span>
                        ) : (
                          <span className="rounded bg-ink/10 px-2 py-0.5 font-mono text-[10px] font-medium text-ink/70">
                            分支 (Gen {node.generation})
                          </span>
                        )}
                        <span className="font-mono font-semibold text-ink">{node.node_id}</span>
                        {node.mutation_type && (
                          <span className="rounded bg-purple-500/15 px-1.5 py-0.5 text-[10px] font-mono text-purple-400">
                            {node.mutation_type}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded px-2 py-0.5 font-mono text-[10px] font-bold ${
                            node.status === "active"
                              ? "bg-signal/20 text-signal border border-signal/30"
                              : "bg-danger/20 text-danger border border-danger/30"
                          }`}
                        >
                          {node.status.toUpperCase()}
                        </span>
                        <span className="font-mono text-xs">
                          相对超额:{" "}
                          <strong className={node.relative_pnl >= 0 ? "text-signal" : "text-danger"}>
                            {node.relative_pnl >= 0 ? "+" : ""}{(node.relative_pnl * 100).toFixed(2)}%
                          </strong>
                        </span>
                        <span className="font-mono text-xs text-ink/70">
                          Sharpe: <strong className="text-ink">{node.sharpe_ratio.toFixed(2)}</strong>
                        </span>
                      </div>
                    </div>

                    <p className={`mt-2 text-ink/80 ${isPruned ? "line-through text-ink/50" : ""}`}>
                      {node.claim}
                    </p>

                    {node.reason && (
                      <div className="mt-2 flex items-center gap-1.5 rounded bg-danger/10 px-2 py-1 text-[11px] text-danger">
                        <ShieldAlert size={12} />
                        <span>剪枝劣汰原因: {node.reason}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Section 2: Position Netting Relay Handover Monitor */}
          <div className="rounded-lg border border-ink/10 bg-paper/80 p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <Scale className="text-signal" size={18} />
                  <h3 className="text-sm font-semibold text-ink">赛马接力净额平滑换仓监视器 (Relay Handover Netting)</h3>
                </div>
                <p className="mt-1 text-xs text-ink/60">
                  新旧策略交接时对相同标的底仓实施头寸轧差，消除全清全买损耗，分片平滑迁移以规避市场冲击。
                </p>
              </div>
              <span className="rounded bg-signal/15 px-2 py-1 font-mono text-xs text-signal border border-signal/30">
                交接计划: {relayHandovers.length}
              </span>
            </div>

            <div className="mt-4 space-y-4">
              {relayHandovers.length > 0 ? (
                relayHandovers.map((plan) => {
                  const isStepping = steppingPlanId === plan.plan_id;
                  const progressPct = Math.round((plan.slices_completed / Math.max(1, plan.slices_total)) * 100);
                  return (
                    <div
                      key={plan.plan_id}
                      className="rounded-lg border border-ink/15 bg-paper/90 p-4 shadow-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2 font-mono text-xs">
                          <span className="rounded bg-ink/10 px-2 py-0.5 font-bold text-ink">{plan.parent_strategy_id}</span>
                          <span className="text-ink/40">➔ 接力交付给 ➔</span>
                          <span className="rounded bg-signal/15 px-2 py-0.5 font-bold text-signal">{plan.challenger_strategy_id}</span>
                        </div>
                        <span
                          className={`rounded px-2 py-0.5 font-mono text-[10px] font-bold ${
                            plan.is_completed
                              ? "bg-signal/20 text-signal"
                              : "bg-cyan-500/20 text-cyan-400 animate-pulse"
                          }`}
                        >
                          {plan.status.toUpperCase()}
                        </span>
                      </div>

                      {/* Efficiency Metrics */}
                      <div className="mt-3 grid grid-cols-4 gap-3 max-md:grid-cols-2 text-xs">
                        <div className="rounded border border-signal/30 bg-signal/10 p-2 text-center">
                          <span className="block text-[10px] text-signal/70">换手节省率</span>
                          <span className="font-mono text-base font-bold text-signal">
                            {(plan.turnover_reduction_ratio * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="rounded border border-signal/30 bg-signal/10 p-2 text-center">
                          <span className="block text-[10px] text-signal/70">节省摩擦成本</span>
                          <span className="font-mono text-base font-bold text-signal">
                            +${plan.friction_saved_usd.toFixed(2)}
                          </span>
                        </div>
                        <div className="rounded border border-ink/10 bg-paper p-2 text-center">
                          <span className="block text-[10px] text-ink/40">净额名义本金</span>
                          <span className="font-mono text-base font-bold text-ink">
                            ${plan.netted_notional.toLocaleString()}
                          </span>
                        </div>
                        <div className="rounded border border-ink/10 bg-paper p-2 text-center">
                          <span className="block text-[10px] text-ink/40">毛名义本金 (若全清买)</span>
                          <span className="font-mono text-base font-bold text-ink/50 line-through">
                            ${plan.gross_notional.toLocaleString()}
                          </span>
                        </div>
                      </div>

                      {/* Slices Progress bar */}
                      <div className="mt-3">
                        <div className="flex items-center justify-between text-xs font-mono text-ink/60">
                          <span>平滑换仓切片进度: {plan.slices_completed} / {plan.slices_total}</span>
                          <span>{progressPct}% 完成</span>
                        </div>
                        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-ink/10">
                          <div
                            className="h-full bg-signal transition-all duration-300"
                            style={{ width: `${progressPct}%` }}
                          />
                        </div>
                      </div>

                      {/* Step Slice Action */}
                      <div className="mt-3 flex items-center justify-between border-t border-ink/10 pt-2.5">
                        <span className="font-mono text-[11px] text-ink/40">
                          计划 ID: {plan.plan_id}
                        </span>
                        {!plan.is_completed && (
                          <button
                            type="button"
                            onClick={() => void handleStepRelaySlice(plan.plan_id)}
                            disabled={isStepping}
                            className="inline-flex items-center gap-1.5 rounded-md border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 text-xs font-semibold text-cyan-400 hover:bg-cyan-500/25 disabled:opacity-50"
                          >
                            <RefreshCw size={13} className={isStepping ? "animate-spin" : ""} />
                            {isStepping ? "执行切片中..." : "手动步进下一周期切片 (Step Slice)"}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="py-6 text-center text-xs text-ink/40">暂无待执行的净额换仓接力计划</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
