import { describe, expect, it } from "vitest";
import { applyAgentEvent, eventActivity, type ChatMessage } from "./conversation";

const baseMessage: ChatMessage = {
  id: "assistant-1",
  role: "assistant",
  text: "",
  state: "streaming"
};

describe("applyAgentEvent", () => {
  it("replaces progress text with the complete audited answer", () => {
    const accepted = applyAgentEvent(baseMessage, {
      event: "answer_delta",
      text: "已受理只读研究请求。"
    });
    const answered = applyAgentEvent(accepted, {
      event: "answer_delta",
      text: "当前证据不足。"
    });
    const completed = applyAgentEvent(answered, {
      event: "final",
      run: {
        report_markdown: "## 结论\n\n已读取策略清单。\n\n## 已验证证据\n\n- 策略 A",
        report_json: {
          operator_response: {
            decision: "当前证据不足。",
            unknowns: ["资金费率缺失"]
          }
        }
      }
    });

    expect(completed.text).toContain("已读取策略清单。");
    expect(completed.text).toContain("策略 A");
    expect(completed.text).not.toContain("已受理只读研究请求。");
    expect(completed.unknowns).toEqual(["资金费率缺失"]);
    expect(completed.state).toBe("complete");
  });

  it("surfaces evidence counts and typed errors", () => {
    const withEvidence = applyAgentEvent(baseMessage, { event: "evidence_ready", count: 4 });
    const failed = applyAgentEvent(withEvidence, {
      event: "error",
      error: { code: "stream_runtime_error" }
    });

    expect(withEvidence.evidenceCount).toBe(4);
    expect(failed.text).toContain("stream_runtime_error");
    expect(failed.state).toBe("error");
    expect(eventActivity({ event: "evidence_ready", count: 4 })).toBe("已验证 4 条证据");
  });
});
