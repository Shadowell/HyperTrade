import type { ProviderStatus, RouteMetric } from "../types";
import type { CSSProperties } from "react";

export function providerLabel(provider: ProviderStatus | undefined, t: Record<string, string>): string {
  if (!provider) {
    return t.missing;
  }
  const model = provider.model || provider.name;
  return `${provider.display_name} / ${model}`;
}

export function formatTokenSource(source: string | undefined, t: Record<string, string>): string {
  if (source === "bitpro_settings_agent_token_or_server_env") {
    return t.mcpTokenSourceSettings;
  }
  return source || "n/a";
}

export function statusLabel(status: string | undefined): string {
  const normalized = (status ?? "").toLowerCase();
  const labels: Record<string, string> = {
    acknowledged: "已确认",
    active: "活跃",
    alive: "在线",
    allowed: "通过",
    approved: "已批准",
    archived: "已归档",
    canceled: "已取消",
    cancelled: "已取消",
    completed: "已完成",
    configured: "已配置",
    connected: "已连接",
    degraded: "降级",
    deterministic: "确定性",
    disabled: "已禁用",
    draining: "交接中",
    error: "异常",
    failed: "失败",
    healthy: "健康",
    missing: "未配置",
    observing: "观察中",
    open: "未解决",
    passed: "通过",
    paused: "已暂停",
    pending: "待处理",
    pending_approval: "待审批",
    preview: "预览",
    ready: "就绪",
    rejected: "已拒绝",
    running: "运行中",
    stale: "陈旧/停滞",
    succeeded: "成功",
    success: "成功",
    tracking: "追踪中",
    transferred: "已交接",
    unknown: "未知",
    waiting_approval: "等待审批",
    waiting_input: "等待输入"
  };
  return labels[normalized] ?? status ?? "未知";
}

export function cascadeStyle(index: number): CSSProperties & Record<"--index", number> {
  return { "--index": index };
}

export function formatMetricNumber(value: number): string {
  if (value >= 1000) {
    return Intl.NumberFormat("en", { notation: "compact" }).format(value);
  }
  return String(value);
}

export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "无数据";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}秒`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}分`;
  }
  return `${Math.floor(seconds / 3600)}时`;
}

export function formatPercentValue(value: string | undefined): string {
  if (!value || value === "n/a") {
    return "n/a";
  }
  return value.endsWith("%") ? value : `${value}%`;
}

export function metricTone(value: string | undefined): RouteMetric["tone"] {
  const numericValue = Number(value?.replace("%", ""));
  if (Number.isFinite(numericValue) && numericValue < 0) {
    return "danger";
  }
  return "signal";
}
