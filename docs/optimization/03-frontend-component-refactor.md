# 优化计划 3：前端组件拆分 + Error Boundary + 状态管理

## 现状诊断

`frontend/src/App.tsx` 单文件 2229 行，包含：
- 30+ TypeScript 类型定义（内联在文件顶部）
- 15+ `useState` hooks
- 8 个主 section（harness、strategy、alerts、runs、memory、rag、telemetry、market）
- 自定义 i18n 函数、markdown 渲染器、数字格式化（内联在文件底部）
- 所有子组件函数（`StructuredReport`、`SourceIdStrip`、`EvidenceMetric` 等）内联在同一个文件
- 仅 5 个测试，只覆盖基本渲染，无 error/loading/edge case 测试

## 目标

三层改造：
1. **组件拆分**：8 个 section → 8 个独立组件 + 17 个共享 UI 组件
2. **Error Boundary**：每个 section 独立错误边界，不全局崩溃
3. **状态管理**：Zustand 替代散落的 useState，消除 prop drilling

## 涉及文件

| 操作 | 文件 |
|------|------|
| 新建 | `frontend/src/types/index.ts` |
| 新建 | `frontend/src/lib/i18n.ts` |
| 新建 | `frontend/src/lib/markdown.ts` |
| 新建 | `frontend/src/lib/format.ts` |
| 新建 | `frontend/src/hooks/useStore.ts` |
| 新建 | `frontend/src/components/ui/StatusDot.tsx` |
| 新建 | `frontend/src/components/ui/MetricCard.tsx` |
| 新建 | `frontend/src/components/ui/EmptyRow.tsx` |
| 新建 | `frontend/src/components/ui/Spinner.tsx` |
| 新建 | `frontend/src/components/ui/Skeleton.tsx` |
| 新建 | `frontend/src/components/ui/ErrorBanner.tsx` |
| 新建 | `frontend/src/components/ui/ErrorBoundary.tsx` |
| 新建 | `frontend/src/components/sidebar/Sidebar.tsx` |
| 新建 | `frontend/src/components/header/Header.tsx` |
| 新建 | `frontend/src/components/telemetry/TelemetryGrid.tsx` |
| 新建 | `frontend/src/components/agent/RunConsole.tsx` |
| 新建 | `frontend/src/components/agent/AgentProgress.tsx` |
| 新建 | `frontend/src/components/agent/ReportReader.tsx` |
| 新建 | `frontend/src/components/agent/ToolTrace.tsx` |
| 新建 | `frontend/src/components/strategy/StrategyPanel.tsx` |
| 新建 | `frontend/src/components/strategy/EvidenceDetail.tsx` |
| 新建 | `frontend/src/components/alerts/AlertsPanel.tsx` |
| 新建 | `frontend/src/components/alerts/ApprovalPanel.tsx` |
| 新建 | `frontend/src/components/memory/MemoryPanel.tsx` |
| 新建 | `frontend/src/components/memory/RagPanel.tsx` |
| 新建 | `frontend/src/components/market/TopMovers.tsx` |
| 新建 | `frontend/src/components/market/RecentRuns.tsx` |
| 新增依赖 | `zustand`（pnpm add zustand） |
| 改造 | `frontend/src/App.tsx` |
| 改造 | `frontend/src/App.test.tsx` |

---

## 目录结构

```
frontend/src/
├── App.tsx                    # 精简至 ~150 行：layout + tab 切换
├── main.tsx                   # 不变
├── styles.css                 # 不变
├── types/
│   └── index.ts               # 所有 TS 类型定义
├── lib/
│   ├── i18n.ts                # T 翻译函数 + Language 类型
│   ├── markdown.ts            # renderMarkdown() 函数
│   └── format.ts              # formatMetricNumber / formatAge 等
├── hooks/
│   └── useStore.ts            # Zustand store
├── components/
│   ├── ui/
│   │   ├── StatusDot.tsx
│   │   ├── MetricCard.tsx
│   │   ├── EmptyRow.tsx
│   │   ├── Spinner.tsx
│   │   ├── Skeleton.tsx
│   │   ├── ErrorBanner.tsx
│   │   └── ErrorBoundary.tsx
│   ├── sidebar/
│   │   └── Sidebar.tsx
│   ├── header/
│   │   └── Header.tsx
│   ├── telemetry/
│   │   └── TelemetryGrid.tsx
│   ├── agent/
│   │   ├── RunConsole.tsx
│   │   ├── AgentProgress.tsx
│   │   ├── ReportReader.tsx
│   │   └── ToolTrace.tsx
│   ├── strategy/
│   │   ├── StrategyPanel.tsx
│   │   └── EvidenceDetail.tsx
│   ├── alerts/
│   │   ├── AlertsPanel.tsx
│   │   └── ApprovalPanel.tsx
│   ├── memory/
│   │   ├── MemoryPanel.tsx
│   │   └── RagPanel.tsx
│   └── market/
│       ├── TopMovers.tsx
│       └── RecentRuns.tsx
```

---

## 详细设计

### 1. types/index.ts

从 `App.tsx` 顶部复制所有类型定义：

- `Language`, `NavSection`, `ProviderStatus`, `HarnessOverview`
- `AgentRun`, `TraceEvent`, `StructuredReportBlock`, `RunState`
- `MemoryItem`, `RagHit`, `RagHitRaw`, `StrategyLibraryItem`, `StrategyLibraryPayload`
- `EvidenceSelection`, `EvidenceSource`, `EvidenceMetric`, `SourceStatus`
- `MonitorAlert`, `LiveOrderIntent`
- 所有 `Record<string, ...>` 的辅助类型

### 2. lib/*.ts

**lib/i18n.ts**：
- `type Language = "zh" | "en"`
- `const translations: Record<Language, Record<string, string>>`
- `export function t(lang: Language, key: string, ...args: string[]): string`

**lib/markdown.ts**：
- `export function renderMarkdown(md: string): string`
- 内联的 `<h1>-<h3>`, `<p>`, `<ul>/<li>`, `<strong>`, `<span>` 等标签转换逻辑

**lib/format.ts**：
- `formatMetricNumber(n: number): string` — K/M/B 缩写
- `formatAge(ts: string | null): string` — 时间差
- `statusLabel(status: string): string` — 状态中英文

### 3. hooks/useStore.ts

```tsx
import { create } from "zustand";
import type {
  HarnessOverview, AgentRun, MemoryItem, RagHit,
  StrategyLibraryPayload, MonitorAlert, EvidenceSelection,
} from "../types";

interface HarnessState {
  overview: HarnessOverview | null;
  overviewError: string;
  overviewLoading: boolean;

  run: AgentRun | null;
  runBusy: boolean;
  agentProgress: string[];

  memoryItems: MemoryItem[];
  selectedMemoryId: string | null;
  memoryQuery: string;

  ragQuery: string;
  ragHits: RagHit[];

  strategyLibrary: StrategyLibraryPayload | null;
  strategyQuery: string;

  monitorAlerts: MonitorAlert[];
  evidenceSelection: EvidenceSelection | null;

  // Actions
  refreshOverview: () => Promise<void>;
  runAgent: (prompt: string) => Promise<void>;
  loadRun: (runId: string) => Promise<void>;
  searchRag: () => Promise<void>;
  searchMemory: (query?: string) => Promise<void>;
  searchStrategy: (query?: string) => Promise<void>;
  refreshAlerts: () => Promise<void>;
  setLanguage: (lang: "zh" | "en") => void;
}
```

每个 action 封装对应的 fetch 调用。组件只需 `useHarnessStore()` 即可获取数据和操作，不再需要 prop drilling。

### 4. Error Boundary

```tsx
// components/ui/ErrorBoundary.tsx
import React, { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[HyperTrade UI Error]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="p-4 border border-red-500/30 rounded-lg bg-red-500/5">
            <p className="text-red-400 text-sm mb-2">
              Component crashed: {this.state.error?.message}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="text-xs text-blue-400 hover:underline cursor-pointer"
            >
              Retry
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
```

在 App.tsx 中包裹每个 section：

```tsx
<ErrorBoundary>
  <StrategyPanel />
</ErrorBoundary>
<ErrorBoundary>
  <AlertsPanel />
</ErrorBoundary>
```

### 5. 组件 4 态模式

每个 section 组件必须处理四种状态：

```tsx
function StrategyPanel() {
  const { strategyLibrary, strategyLibraryLoading, strategyLibraryError } = useHarnessStore();

  // 1. Loading
  if (strategyLibraryLoading) return <Skeleton rows={3} />;

  // 2. Error
  if (strategyLibraryError) {
    return <ErrorBanner message={strategyLibraryError} onRetry={...} />;
  }

  // 3. Empty
  if (!strategyLibrary?.items?.length) {
    return <EmptyRow label="暂无策略数据" />;
  }

  // 4. Normal
  return (
    <div>
      {strategyLibrary.items.map(item => <EvidenceCard key={item.id} {...item} />)}
    </div>
  );
}
```

---

## 实施顺序

按照依赖从低到高的顺序拆分，每一步确保 `pnpm build` 通过：

1. **抽出类型和工具函数**（无业务依赖，影响面最小）
   - 建 `types/index.ts` — 复制所有类型
   - 建 `lib/i18n.ts` — 复制 T 函数和翻译表
   - 建 `lib/markdown.ts` — 复制 renderMarkdown
   - 建 `lib/format.ts` — 复制格式化函数
   - 更新 App.tsx 的 import，验证 build

2. **建 UI 基础组件**（无业务依赖，可复用）
   - `StatusDot.tsx`, `MetricCard.tsx`, `EmptyRow.tsx`
   - `Spinner.tsx`, `Skeleton.tsx`
   - `ErrorBanner.tsx`, `ErrorBoundary.tsx`

3. **引入 Zustand**
   - `pnpm add zustand`
   - 建 `hooks/useStore.ts`
   - 逐个将 App.tsx 中的 fetch 逻辑迁移到 store actions

4. **从叶子组件开始拆 section**（顺序: 内层→外层）
   - `RecentRuns.tsx`（最简单，只渲染列表）
   - `TopMovers.tsx`
   - `RagPanel.tsx`
   - `MemoryPanel.tsx`
   - `EvidenceDetail.tsx`
   - `StrategyPanel.tsx`
   - `ToolTrace.tsx`
   - `ReportReader.tsx`
   - `AgentProgress.tsx`
   - `RunConsole.tsx`
   - `ApprovalPanel.tsx`
   - `AlertsPanel.tsx`
   - `TelemetryGrid.tsx`
   - `Header.tsx`
   - `Sidebar.tsx`

5. **精简 App.tsx**
   - 删除所有内联组件和类型
   - 只剩 layout（grid）+ tab 切换逻辑
   - 每个 section 包裹 ErrorBoundary

6. **更新测试**
   - `App.test.tsx` 适配新组件结构
   - 加每个 section 组件的独立测试

---

## 验收标准

1. `App.tsx` ≤ 200 行
2. 每个 section 组件有独立的 loading / error / empty / normal 四种 UI 状态
3. ErrorBoundary 包裹所有 section，单个组件崩溃不影响其他区域
4. 前端构建产物中无循环依赖（pnpm build 无警告）
5. `pnpm lint` && `pnpm test` && `pnpm build` 全部通过
6. `./scripts/check.sh` 通过

## 面试可讲点

- **组件化设计**：单一职责、可复用、可测试 — — 面试官期望的不是"能跑就行"而是"可维护"
- **Error Boundary**：React 16+ 特性，展示对 React 错误处理机制的理解
- **Zustand vs Redux**：为什么选轻量方案？个人项目的实用主义 vs 团队项目的标准化
- **4 态 UI**：loading / error / empty / normal — — 这是企业级 UI 开发的基本素养
- **Props Drilling 问题**：Zustand 提供全局 store，组件直接访问数据，不需要层层传递
