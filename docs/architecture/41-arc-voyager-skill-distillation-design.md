# 41 ARC Voyager 风格技能自动提取与基因库技术设计 (Skill Distillation)

> 文档性质：组件级技术设计规范与代码技能提取指南。
> 状态：Approved & Active — 2026-07-30。

## 1. 概述与设计背景

在长期的自主探索过程中，如果 Agent 每次都“从零编写整套策略”，过去探索出的优质因子或风控逻辑就会随之丢弃。

**ARC Voyager 风格技能自动提取与基因库**（`ARCSkillDistiller` 与 `ARCSkillLibrary`）借鉴了顶级 AI 代理 Voyager 的进化思想：
* 每当一个策略候选击败红队攻击并通过确定性验证后，蒸馏器自动扫描该策略的 AST 语法树。
* 自动提取出优良的子函数（如自适应通道计算、订单簿失衡退出算法）。
* 将其类型化、文档化注册进不可变技能库，并格式化为标准 Markdown/Python 语法块，直接注入到后续演化轮次的蓝队 LLM 提示词上下文中。

---

## 2. AST 技能提取与注入流程

```text
[策略通过验证/上线模拟盘]
           │
           ▼
[ARCSkillDistiller 扫描 AST 语法树]
           │
           ▼
[发现 Helper 子函数 (如 FunctionDef)] ──► [生成类型标注与 Docstring 说明]
                                                   │
                                                   ▼
[注册到 ARCSkillLibrary 基因库] ──► [格式化为 API 文档 Inject 到蓝队 Prompt]
```

提取后的技能示例：
```python
### Available Validated Modular Skills Library:
- **compute_volatility_channel** (`skill_compute_volatility_channel_att001`): Automated distilled skill 'compute_volatility_channel' from validated candidate
```python
def compute_volatility_channel(self, candles):
    prices = [c['close'] for c in candles]
    return max(prices) - min(prices)
```

---

## 3. 代码接口与类设计

组件代码位于 [backend/src/hypertrade/arc/skills.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/backend/src/hypertrade/arc/skills.py)：

```python
class ARCSkill(BaseModel):
    skill_id: str
    name: str
    description: str
    code_snippet: str
    provenance_candidate_id: str
    tags: list[str] = Field(default_factory=list)
    usage_count: int = 0


class ARCSkillLibrary:
    def register_skill(self, skill: ARCSkill) -> bool: ...
    def format_skills_for_prompt(self) -> str: ...


class ARCSkillDistiller:
    def distill_skills_from_candidate(
        self, attempt: ARCCandidateAttemptV1
    ) -> list[ARCSkill]: ...
```

---

## 4. 单元与集成测试

详见 [tests/test_arc_skills.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/tests/test_arc_skills.py)：

```bash
python3 -m pytest tests/test_arc_skills.py -v
```
测试验证了 AST 节点提取、代码块剥离、技能库注册与 Prompt 文档格式化。
