import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Radio } from "lucide-react";
import { afterEach, expect, test, vi } from "vitest";
import { copy } from "../../i18n/messages";
import { liveOverview } from "../../test/fixtures";
import type { TraceEvent } from "../../types";
import { AgentProgress } from "./AgentProgress";
import { HarnessHeader } from "./HarnessHeader";
import { ReportReader } from "./ReportReader";
import { RunControls } from "./RunControls";
import { RuntimeMonitor } from "./RuntimeMonitor";
import { TelemetryGrid } from "./TelemetryGrid";

const t = copy.zh;

afterEach(cleanup);

// --- HarnessHeader -------------------------------------------------------------------------

function header(props: Partial<Parameters<typeof HarnessHeader>[0]> = {}) {
  return render(
    <HarnessHeader
      access="unknown"
      generatedAt={null}
      language="zh"
      refreshing={false}
      sync="connecting"
      t={t}
      {...props}
    />
  );
}

test("while connecting the header says so and shows no timestamp", () => {
  header();
  expect(screen.getAllByText(t.overviewConnecting).length).toBeGreaterThanOrEqual(1);
  expect(document.querySelector("time")).toBeNull();
});

test("once synced the header shows a localized time with the machine-readable value", () => {
  header({ generatedAt: "2026-11-10T12:52:38+00:00", sync: "ready" });

  const time = document.querySelector("time");
  expect(time).not.toBeNull();
  expect(time).toHaveAttribute("datetime", "2026-11-10T12:52:38+00:00");
  expect(time?.textContent).toMatch(/2026/);
  expect(time?.textContent).not.toContain("T12:52:38"); // not the raw ISO string
  expect(screen.getByText(t.healthy)).toBeInTheDocument();
});

test("an unreachable overview is reported as unavailable, never as healthy", () => {
  header({ sync: "unavailable" });
  expect(screen.getAllByText(t.overviewUnavailable).length).toBeGreaterThanOrEqual(1);
  expect(screen.queryByText(t.healthy)).not.toBeInTheDocument();
});

test("an unparsable timestamp does not crash the header", () => {
  header({ generatedAt: "garbage", sync: "ready" });
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(t.workbenchTitle);
  expect(document.querySelector("time")).toBeNull();
});

test("the read-only badge appears only after a privileged call was refused", () => {
  const { unmount } = header({ access: "unknown" });
  expect(screen.queryByText(t.readOnlyBadge)).not.toBeInTheDocument();
  unmount();

  header({ access: "readonly" });
  expect(screen.getByText(t.readOnlyBadge)).toBeInTheDocument();
});

// --- TelemetryGrid -------------------------------------------------------------------------

test("telemetry shows placeholders, not zeros, until the overview has arrived", () => {
  const metrics = [{ label: "行情覆盖", value: "344", icon: Radio, tone: "signal" }];
  const { rerender } = render(<TelemetryGrid label="概览" loading metrics={metrics} />);

  const region = screen.getByRole("region", { name: "概览" });
  expect(region).toHaveAttribute("aria-busy", "true");
  expect(within(region).queryByText("344")).not.toBeInTheDocument();
  expect(within(region).getByText("—")).toBeInTheDocument();

  rerender(<TelemetryGrid label="概览" loading={false} metrics={metrics} />);
  expect(screen.getByText("344")).toBeInTheDocument();
});

// --- RunControls ---------------------------------------------------------------------------

function controls(props: Partial<Parameters<typeof RunControls>[0]> = {}) {
  const handlers = {
    onPromptChange: vi.fn(),
    onRun: vi.fn(),
    onNewThread: vi.fn(),
    onArchiveThread: vi.fn()
  };
  render(
    <RunControls
      access="unknown"
      busy={false}
      error=""
      hasThread={false}
      prompt="分析 BTC"
      t={t}
      thread={null}
      turnActive={false}
      {...handlers}
      {...props}
    />
  );
  return handlers;
}

test("the prompt box has an accessible name and reports edits", () => {
  const { onPromptChange } = controls();

  const box = screen.getByLabelText(t.promptLabel);
  fireEvent.change(box, { target: { value: "分析 ETH" } });

  expect(onPromptChange).toHaveBeenCalledWith("分析 ETH");
});

test("the actions call their handlers", () => {
  const { onRun, onNewThread, onArchiveThread } = controls({ hasThread: true });

  fireEvent.click(screen.getByRole("button", { name: t.run }));
  fireEvent.click(screen.getByRole("button", { name: t.newThread }));
  fireEvent.click(screen.getByRole("button", { name: t.archiveThread }));

  expect(onRun).toHaveBeenCalledOnce();
  expect(onNewThread).toHaveBeenCalledOnce();
  expect(onArchiveThread).toHaveBeenCalledOnce();
});

test("read-only mode disables every privileged action and says how to sign in", () => {
  controls({ access: "readonly", hasThread: true });

  expect(screen.getByRole("button", { name: t.run })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.newThread })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.archiveThread })).toBeDisabled();
  const note = screen.getByRole("note");
  expect(note).toHaveTextContent(t.readOnlyTitle);
  expect(note).toHaveTextContent("ht /login");
});

test("while a turn is running the operator can neither start nor archive, only open a new thread", () => {
  controls({ hasThread: true, turnActive: true });

  expect(screen.getByRole("button", { name: t.run })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.archiveThread })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.newThread })).toBeEnabled();
});

test("archiving needs a thread, and everything waits while busy", () => {
  controls({ hasThread: false });
  expect(screen.getByRole("button", { name: t.archiveThread })).toBeDisabled();
  cleanup();

  controls({ busy: true, hasThread: true });
  expect(screen.getByRole("button", { name: t.run })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.newThread })).toBeDisabled();
});

test("an error is announced as an alert and thread metadata is shown", () => {
  controls({
    error: "无法连接后端，请稍后重试。",
    thread: { id: "thr_1", cursor: 42, reconnecting: false }
  });

  expect(screen.getByRole("alert")).toHaveTextContent("无法连接后端");
  expect(screen.getByText("thr_1")).toBeInTheDocument();
  expect(screen.getByText("cursor=42")).toBeInTheDocument();
  expect(screen.getByText(t.threadReady)).toBeInTheDocument();
});

// --- AgentProgress -------------------------------------------------------------------------

test("with no progress the panel says so instead of showing a loading message", () => {
  render(<AgentProgress items={[]} stage={null} t={t} />);

  const live = screen.getByRole("status", { name: t.agentProgress });
  expect(live).toHaveAttribute("aria-live", "polite");
  expect(within(live).getByText(t.noProgressYet)).toBeInTheDocument();
  expect(within(live).getByText("—")).toBeInTheDocument();
  expect(screen.queryByText(t.overviewLoading)).not.toBeInTheDocument();
});

test("steps and the current stage are listed", () => {
  render(<AgentProgress items={["market.summary ready", "rag.search ready"]} stage="running" t={t} />);

  expect(screen.getByText("running")).toBeInTheDocument();
  expect(screen.getByText("market.summary ready")).toBeInTheDocument();
  expect(screen.getByText("rag.search ready")).toBeInTheDocument();
  expect(screen.queryByText(t.noProgressYet)).not.toBeInTheDocument();
});

// --- ReportReader --------------------------------------------------------------------------

function reader(props: Partial<Parameters<typeof ReportReader>[0]> = {}) {
  const onToggleRaw = vi.fn();
  render(
    <ReportReader
      blocks={[]}
      busy={false}
      markdown=""
      onToggleRaw={onToggleRaw}
      showRaw={false}
      t={t}
      {...props}
    />
  );
  return { onToggleRaw };
}

test("with no run there is an honest empty state and no invented report", () => {
  reader();

  expect(screen.getByText(t.noRunYet)).toBeInTheDocument();
  expect(screen.getByText(t.noRunYetHint)).toBeInTheDocument();
  expect(screen.queryByText(/BTC-USDT-SWAP/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: t.rawMarkdown })).not.toBeInTheDocument();
});

test("a running turn shows the loading text, not the empty state", () => {
  reader({ busy: true });
  expect(screen.queryByText(t.noRunYet)).not.toBeInTheDocument();
});

test("a report is rendered and can be flipped to raw markdown", () => {
  const { onToggleRaw } = reader({ markdown: "# 标题\n\n- 要点一" });

  expect(screen.getByRole("heading", { name: "标题" })).toBeInTheDocument();
  expect(screen.getByText("要点一")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: t.rawMarkdown }));
  expect(onToggleRaw).toHaveBeenCalledOnce();
});

test("raw mode shows the markdown source verbatim", () => {
  reader({ markdown: "# 标题", showRaw: true });
  expect(screen.getByText("# 标题")).toBeInTheDocument();
});

// --- RuntimeMonitor ------------------------------------------------------------------------

function monitor(props: Partial<Parameters<typeof RuntimeMonitor>[0]> = {}) {
  const handlers = { onRefresh: vi.fn(), onSelectTraceEvidence: vi.fn() };
  render(
    <RuntimeMonitor
      defaultProvider={undefined}
      overview={null}
      refreshing={false}
      sync="connecting"
      t={t}
      traceEvents={[]}
      {...handlers}
      {...props}
    />
  );
  return handlers;
}

test("while connecting the tool heading stays and the body is a placeholder, not sample data", () => {
  monitor();

  expect(screen.getByText(t.tools)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(t.overviewConnecting);
  expect(screen.queryByText(t.bitproMcp)).not.toBeInTheDocument();
  expect(screen.queryByText(/文档/)).not.toBeInTheDocument();
});

test("an unreachable overview offers a retry instead of a fixture", () => {
  const { onRefresh } = monitor({ sync: "unavailable" });

  expect(screen.getByRole("alert")).toHaveTextContent(t.overviewUnavailable);
  fireEvent.click(screen.getByRole("button", { name: t.retry }));
  expect(onRefresh).toHaveBeenCalledOnce();
  expect(screen.queryByText(t.bitproMcp)).not.toBeInTheDocument();
});

test("with an overview it lists tool calls, counts and the BitPro connection", () => {
  const events: TraceEvent[] = [
    { id: "t1", tool_name: "market.summary", status: "ready" },
    { id: "t2", tool_name: "rag.search", status: "ready" }
  ];
  const overview = liveOverview();
  const { onSelectTraceEvidence } = monitor({
    overview,
    sync: "ready",
    traceEvents: events,
    defaultProvider: overview.providers[0]
  });

  expect(screen.getByText("Codex / gpt-6-astra")).toBeInTheDocument();
  expect(screen.getByText(/12 文档 \/ 340 分片/)).toBeInTheDocument();
  expect(screen.getByText(/7 可用 \/ 9 总数/)).toBeInTheDocument();
  expect(screen.getByText(t.bitproMcp)).toBeInTheDocument();
  expect(screen.getByText("https://bitpro.example/api/v2")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /rag\.search/ }));
  expect(onSelectTraceEvidence).toHaveBeenCalledWith(events[1]);
});

test("no tool calls yet is stated, and the BitPro card is omitted when it is not configured", () => {
  monitor({ overview: liveOverview({ bitpro: undefined }), sync: "ready" });

  expect(screen.getByText(t.noToolCalls)).toBeInTheDocument();
  expect(screen.queryByText(t.bitproMcp)).not.toBeInTheDocument();
});

test("refresh is disabled while a refresh is already running", () => {
  monitor({ refreshing: true, overview: liveOverview(), sync: "ready" });
  expect(screen.getByRole("button", { name: t.refresh })).toBeDisabled();
});
