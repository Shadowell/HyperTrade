import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  Dna,
  RefreshCw,
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

type ViewTab = "execution" | "matrix";

export function QuantumPortfolioDashboard() {
  const [activeTab, setActiveTab] = useState<ViewTab>("execution");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [registryRecords, setRegistryRecords] = useState<StrategyRegistryRecord[]>([]);
  const [evolutionHistory, setEvolutionHistory] = useState<EvolutionEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [rebalancing, setRebalancing] = useState(false);
  const [evolvingKey, setEvolvingKey] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const fetchDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, regRes, histRes] = await Promise.all([
        fetch("/api/portfolio/summary", { credentials: "include" }),
        fetch("/api/portfolio/registry", { credentials: "include" }),
        fetch("/api/portfolio/evolution/history", { credentials: "include" }),
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

        {/* Tab Switcher & Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-ink/15 bg-paper p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setActiveTab("execution")}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "execution" ? "bg-ink/10 text-ink shadow-sm" : "text-ink/60 hover:text-ink"
              }`}
            >
              <Activity size={14} />
              执行总览与盯市
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("matrix")}
              className={`flex items-center gap-1.5 rounded px-3 py-1.5 font-medium transition-all ${
                activeTab === "matrix" ? "bg-ink/10 text-ink shadow-sm" : "text-ink/60 hover:text-ink"
              }`}
            >
              <Dna size={14} />
              策略矩阵与自愈
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
    </div>
  );
}
