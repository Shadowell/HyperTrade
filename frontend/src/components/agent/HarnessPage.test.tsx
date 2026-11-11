import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { presentThread } from "../../agentThread";
import { copy } from "../../i18n/messages";
import { liveOverview } from "../../test/fixtures";
import { HarnessPage, type HarnessPageProps } from "./HarnessPage";

const t = copy.zh;

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function props(overrides: Partial<HarnessPageProps> = {}): HarnessPageProps {
  return {
    t,
    language: "zh",
    sync: "ready",
    overview: liveOverview(),
    refreshing: false,
    onRefresh: vi.fn(),
    access: "unknown",
    metrics: [],
    run: {
      prompt: "分析 BTC",
      onPromptChange: vi.fn(),
      busy: false,
      turnActive: false,
      hasThread: false,
      thread: null,
      error: "",
      onRun: vi.fn(),
      onNewThread: vi.fn(),
      onArchiveThread: vi.fn(),
      stage: null,
      progress: [],
      presentation: presentThread(null),
      report: { markdown: "", blocks: [], showRaw: false, onToggleRaw: vi.fn() }
    },
    monitor: { traceEvents: [], onSelectTraceEvidence: vi.fn(), defaultProvider: undefined },
    observability: { data: null, loading: false },
    ...overrides
  };
}

test("renders the whole workbench for a healthy overview", () => {
  render(<HarnessPage {...props()} />);

  expect(screen.getByRole("heading", { level: 1, name: t.workbenchTitle })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: t.runConsole })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: t.runtimeMonitor })).toBeInTheDocument();
  expect(screen.getByText(t.noRunYet)).toBeInTheDocument();
});

test("a crash in the run console leaves the runtime monitor and the header working", () => {
  const broken = props();
  // ThreadDetails reads presentation.resolvedRefs: an undefined presentation makes it throw.
  broken.run = { ...broken.run, presentation: undefined as never };

  render(<HarnessPage {...broken} />);

  expect(screen.getByRole("alert")).toHaveTextContent(t.sectionCrashed);
  expect(screen.getByRole("heading", { level: 1, name: t.workbenchTitle })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: t.runtimeMonitor })).toBeInTheDocument();
  expect(screen.getByText(t.bitproMcp)).toBeInTheDocument();
});

test("a crash in the header does not blank the console", () => {
  // formatTimestamp tolerates bad input, so force the header itself to throw.
  const broken = props({ language: undefined as never });

  render(<HarnessPage {...broken} />);

  expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByRole("heading", { name: t.runConsole })).toBeInTheDocument();
});

test("before the overview arrives nothing is invented: placeholders and an empty report", () => {
  render(<HarnessPage {...props({ overview: null, sync: "connecting" })} />);

  expect(screen.getAllByText(t.overviewConnecting).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(t.tools)).toBeInTheDocument();
  expect(screen.queryByText(t.bitproMcp)).not.toBeInTheDocument();
  expect(screen.getByText(t.noRunYet)).toBeInTheDocument();
});
