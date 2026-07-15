import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AssistantMarkdown from "./AssistantMarkdown";

describe("AssistantMarkdown", () => {
  it("renders structured Mission output without exposing Markdown markers", () => {
    const { container } = render(
      <AssistantMarkdown
        source={`## 策略运行概览

4. **#304** BTC/ETH/SOL · VWAP 成交量分布趋势
   - 状态：\`running\`
   - 当前收益：**2.80%**

| 证据 | 状态 |
| --- | --- |
| 行情快照 | 已验证 |`}
      />
    );

    expect(screen.getByRole("heading", { name: "策略运行概览" })).toBeInTheDocument();
    expect(screen.getByText("2.80%").tagName).toBe("STRONG");
    expect(screen.getByText("running").tagName).toBe("CODE");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("**");
  });

  it("does not execute raw HTML from an assistant response", () => {
    const { container } = render(
      <AssistantMarkdown source={'<script data-testid="unsafe">alert("x")</script>安全结论'} />
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
  });
});
