import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("HyperTrade desktop bot", () => {
  it("renders the Mission-first research surface in browser preview", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "研究助手" })).toBeInTheDocument();
    expect(screen.getByLabelText("研究问题")).toBeInTheDocument();
    expect(screen.getByText(/交易密钥与执行权限不进入桌面端/)).toBeInTheDocument();
    expect(await screen.findByText("服务已连接")).toBeInTheDocument();
  });

  it("places HT conclusions on the left and user questions on the right", async () => {
    const { container } = render(<App />);
    await screen.findByText("服务已连接");

    fireEvent.change(screen.getByLabelText("研究问题"), {
      target: { value: "验证 BTC 波动风险" }
    });
    fireEvent.click(screen.getByRole("button", { name: "发送研究问题" }));

    expect(await screen.findByText("验证 BTC 波动风险")).toBeInTheDocument();
    expect(container.querySelector(".message-user")).toHaveTextContent("你的问题");
    expect(container.querySelector(".message-assistant")).toHaveTextContent("HT 结论");
  });
});
