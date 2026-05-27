import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import App from "./App";

test("renders harness and market summary surfaces", () => {
  render(<App />);

  expect(screen.getAllByText("Harness").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("行情摘要").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("Tool Call Trace")).toBeInTheDocument();
  expect(screen.getAllByText("OKX SWAP").length).toBeGreaterThanOrEqual(1);
});
