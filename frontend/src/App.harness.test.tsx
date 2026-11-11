import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";
import { copy } from "./i18n/messages";
import { jsonResponse, liveOverview } from "./test/fixtures";

const t = copy.zh;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/harness");
});

type Handler = (init?: RequestInit) => Response;

/** Routes `fetch` by URL suffix; anything unlisted is a 404, like an unconfigured endpoint. */
function mockApi(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [suffix, respond] of Object.entries(handlers)) {
      if (url.endsWith(suffix)) return respond(init);
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("an unreachable overview is stated plainly and sample data is never shown", async () => {
  mockApi({ "/api/harness/overview": () => jsonResponse({ detail: "down" }, 503) });

  render(<App />);

  expect((await screen.findAllByText(t.overviewUnavailable)).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByRole("alert")).toHaveTextContent(t.overviewUnavailableHint);
  // the fixture this page used to fall back to
  expect(screen.queryByText(/70000/)).not.toBeInTheDocument();
  expect(screen.queryByText(/OKX 永续合约行情归纳/)).not.toBeInTheDocument();
  expect(screen.queryByText(t.bitproMcp)).not.toBeInTheDocument();
  expect(screen.queryByText(t.healthy)).not.toBeInTheDocument();
  expect(screen.getByText(t.noRunYet)).toBeInTheDocument();
});

test("Retry loads the overview once the backend is back", async () => {
  let calls = 0;
  mockApi({
    "/api/harness/overview": () => {
      calls += 1;
      return calls === 1 ? jsonResponse({ detail: "down" }, 503) : jsonResponse(liveOverview());
    }
  });

  render(<App />);
  await screen.findAllByText(t.overviewUnavailable);

  fireEvent.click(screen.getByRole("button", { name: t.retry }));

  expect(await screen.findByText(t.bitproMcp)).toBeInTheDocument();
  expect(screen.queryByText(t.overviewUnavailable)).not.toBeInTheDocument();
  expect(screen.getByText(t.healthy)).toBeInTheDocument();
  expect(calls).toBe(2);
});

test("a refused run explains the read-only mode instead of printing 'Not authenticated'", async () => {
  const fetchMock = mockApi({
    "/api/harness/overview": () => jsonResponse(liveOverview()),
    "/api/agent/v1/threads": () => jsonResponse({ detail: "Not authenticated" }, 401)
  });

  render(<App />);
  await screen.findByText(t.bitproMcp);
  expect(screen.getByRole("button", { name: t.run })).toBeEnabled();

  fireEvent.click(screen.getByRole("button", { name: t.run }));

  // The raw server text is replaced by an instruction the operator can act on.
  expect(await screen.findByText(t.errorNotAuthenticated)).toBeInTheDocument();
  expect(screen.queryByText("Not authenticated")).not.toBeInTheDocument();
  expect(screen.getByText(t.readOnlyBadge)).toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent("ht /login");
  expect(screen.getByRole("button", { name: t.run })).toBeDisabled();
  expect(screen.getByRole("button", { name: t.newThread })).toBeDisabled();

  // Product decision pinned by App.test.tsx too: the console never probes the session and has
  // no login form; it only learns it is read-only when an action is refused.
  expect(fetchMock).not.toHaveBeenCalledWith("/api/auth/me", expect.anything());
  expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
});

test("the actions are enabled before anything is refused: the page does not guess it is read-only", async () => {
  mockApi({ "/api/harness/overview": () => jsonResponse(liveOverview()) });

  render(<App />);
  await screen.findByText(t.bitproMcp);

  expect(screen.queryByText(t.readOnlyBadge)).not.toBeInTheDocument();
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: t.run })).toBeEnabled();
});

test("no report is invented before the first run", async () => {
  mockApi({ "/api/harness/overview": () => jsonResponse(liveOverview()) });

  render(<App />);
  await screen.findByText(t.bitproMcp);

  expect(screen.getByText(t.noRunYet)).toBeInTheDocument();
  expect(screen.queryByText(/最新价 70000/)).not.toBeInTheDocument();
  expect(screen.getByText(t.noProgressYet)).toBeInTheDocument();
});

test("one failing section endpoint does not stop the sections loaded after it", async () => {
  window.history.replaceState({}, "", "/harness/alerts");
  mockApi({
    "/api/harness/overview": () => jsonResponse(liveOverview()),
    // the first section loader rejects; the old serial chain stopped right here
    "/api/memory": () => {
      throw new TypeError("Failed to fetch");
    },
    "/api/alerts": () =>
      jsonResponse({
        items: [{ id: "al_1", severity: "high", title: "Funding spike", message: "above threshold" }]
      })
  });

  render(<App />);

  expect(await screen.findByText("Funding spike")).toBeInTheDocument();
});

test("the sidebar stays in view while the page scrolls", async () => {
  mockApi({ "/api/harness/overview": () => jsonResponse(liveOverview()) });

  render(<App />);
  await screen.findByText(t.bitproMcp);

  expect(screen.getByRole("complementary")).toHaveClass("lg:sticky", "lg:top-0");
});
