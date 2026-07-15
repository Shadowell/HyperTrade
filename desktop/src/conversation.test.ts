import { describe, expect, it } from "vitest";
import { applyAgentEvent, eventActivity, type ChatMessage } from "./conversation";

const baseMessage: ChatMessage = {
  id: "assistant-1",
  role: "assistant",
  text: "",
  state: "streaming"
};

describe("applyAgentEvent", () => {
  it("keeps ordered answer deltas without duplicating the final decision", () => {
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
        report_json: {
          operator_response: {
            decision: "当前证据不足。",
            unknowns: ["资金费率缺失"]
          }
        }
      }
    });

    expect(completed.text).toBe("已受理只读研究请求。\n\n当前证据不足。");
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
