import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

let shouldThrow = true;

function Fragile() {
  if (shouldThrow) throw new Error("kaboom");
  return <div>recovered</div>;
}

beforeEach(() => {
  shouldThrow = true;
  // React logs the caught error; keep the test output readable.
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("a crashing child is replaced by a fallback and does not take its siblings down", () => {
  render(
    <>
      <div>sibling</div>
      <ErrorBoundary retryLabel="重试" title="出错了">
        <Fragile />
      </ErrorBoundary>
    </>
  );

  expect(screen.getByText("sibling")).toBeInTheDocument();
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("出错了");
  expect(alert).toHaveTextContent("kaboom");
});

test("Retry re-renders the child once the cause is gone", () => {
  render(
    <ErrorBoundary retryLabel="重试" title="出错了">
      <Fragile />
    </ErrorBoundary>
  );

  shouldThrow = false;
  fireEvent.click(screen.getByRole("button", { name: "重试" }));

  expect(screen.getByText("recovered")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a boundary resets itself when its resetKey changes", () => {
  const { rerender } = render(
    <ErrorBoundary resetKey="a" retryLabel="重试" title="出错了">
      <Fragile />
    </ErrorBoundary>
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();

  shouldThrow = false;
  rerender(
    <ErrorBoundary resetKey="b" retryLabel="重试" title="出错了">
      <Fragile />
    </ErrorBoundary>
  );

  expect(screen.getByText("recovered")).toBeInTheDocument();
});

test("healthy children render untouched", () => {
  shouldThrow = false;
  render(
    <ErrorBoundary retryLabel="重试" title="出错了">
      <Fragile />
    </ErrorBoundary>
  );
  expect(screen.getByText("recovered")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
