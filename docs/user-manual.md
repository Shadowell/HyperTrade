# HyperTrade 用户手册

## 目录

- [概述](#概述)
- [快速开始](#快速开始)
- [CLI 使用指南](#cli-使用指南)
- [Web 界面使用](#web-界面使用)
- [市场研究工作流](#市场研究工作流)
- [策略研究与回测](#策略研究与回测)
- [模拟盘管理](#模拟盘管理)
- [实盘操作](#实盘操作)
- [BitPro 集成](#bitpro-集成)
- [RAG 与 Memory](#rag-与-memory)
- [监控与告警](#监控与告警)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

---

## 概述

HyperTrade 是一个 Agent 驱动的加密货币交易研究与执行框架。它为操作员、工程师和外部 Agent 提供统一的运行时环境，支持市场研究、工具调用、策略迭代、模拟盘执行、BitPro 诊断、追踪、Memory、RAG 和部署操作。

### 核心功能

- **市场研究**：实时 OKX SWAP 市场数据、行情分析、技术指标
- **策略研究**：策略开发、回测、多变体实验、证据管理
- **模拟盘交易**：无风险模拟交易环境
- **实盘执行**：受控的 OKX Testnet 订单执行（V1 阻止主网交易）
- **BitPro 集成**：通过 MCP 适配器访问 BitPro 策略、回测和监控
- **智能 Agent**：自然语言交互，自动工具选择
- **知识管理**：RAG 文档检索和 Memory 系统

### 用户角色

| 角色 | 主要任务 | 使用界面 |
|------|----------|----------|
| 操作员 | 提出市场/实盘/模拟盘问题，检查报告，审查追踪，批准受保护的 Testnet 操作 | CLI `hypertrade`/`ht`，Web `/harness`，REST API |
| 工程师 | 添加工具、提供者、连接器、评估、运行手册和部署检查 | 代码库，`docs/contracts`，`scripts/check.sh` |
| 外部 Agent | 调用稳定的 API/工具接口，无需直接访问密钥或 BitPro 内部 | REST/SSE API，ToolRegistry 元数据，连接器能力 API |

---

## 快速开始

### 前置条件

- Python 3.12+
- `uv` 包管理器
- Node.js 和 `pnpm`
- 聊天提供者 API 密钥（如 DeepSeek）

### 本地安装

1. **克隆仓库**：
   ```bash
   git clone git@github.com:Shadowell/HyperTrade.git
   cd HyperTrade
   ```

2. **配置环境**：
   ```bash
   cp .env.example .env
   # 编辑 .env 文件，设置必要的 API 密钥
   ```

   最小配置示例：
   ```bash
   export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
   export KNOWLEDGE_DIR="docs/knowledge"
   export DEEPSEEK_API_KEY="your-api-key-here"
   ```

3. **启动后端**：
   ```bash
   DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db" \
   KNOWLEDGE_DIR="docs/knowledge" \
   DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
   uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
   ```

4. **启动前端**（另一个终端）：
   ```bash
   npm exec --yes pnpm@10 -- -C frontend install
   npm exec --yes pnpm@10 -- -C frontend dev
   ```

5. **访问界面**：
   - Web 界面：http://localhost:3333/harness
   - API 文档：http://localhost:3334/docs
   - 健康检查：http://localhost:3334/api/health

---

## CLI 使用指南

### 启动 CLI

**本地模式**（直接连接本地数据库）：
```bash
DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db" \
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
uv run ht --local
```

**远程模式**（连接远程 API）：
```bash
# 首次配置远程连接
uv run ht /login

# 之后直接使用
uv run ht
```

**单次查询模式**：
```bash
uv run hypertrade --local ask "看下目前市场的热度怎么样"
```

### 基础命令

#### 系统信息

```bash
/help           # 显示帮助信息
/status         # 系统状态概览
/model          # 查看和切换聊天提供者/模型
/tools          # 列出所有可用工具
/evals          # 查看评估套件状态
/connectors     # 查看连接器状态
/sessions       # 查看持久 Agent 会话
/tasks          # 查看后台和前台 Agent 任务
/task task_*    # 查看任务、预算、事件游标和 checkpoint
```

`/evals` 是离线确定性门禁，当前显示 40 条用例，其中 26 条属于
`research_os_golden_v2`，并按 chat/tool/graph/safety cohort 展示固定分母。它不会发起真实模型调用。Promptfoo/Ragas 只能由运维人员
在服务器隔离 API 上运行，其低分或通过结果都不能启动模拟盘或实盘。

### Agent 任务控制

每次新的本地或远程 Agent 请求都会创建持久 Task。Run 代表一次执行尝试，Task 负责
暂停、恢复、取消、重试、分支和故障恢复：

```bash
/task task_abc pause "等待人工复核"
/task task_abc resume "复核完成"
/task task_abc cancel "研究目标已撤销"
/task task_abc retry "上游 Provider 已恢复"
/task task_abc branch "保留原任务并测试相邻假设"
```

控制操作需要管理员登录。相同 idempotency key 不会重复执行状态变更；Provider 超时
会显示为可重试 Task 错误，而不是丢失运行上下文。后台 queued Task 由 worker 领取，
CLI/API 断线后仍可通过 Task id 和事件游标恢复查看。

### TUI 研究工作台

本地安装可选依赖后启动：

```bash
uv sync --extra tui
uv run ht --remote http://127.0.0.1:3334 tui
uv run ht --remote http://127.0.0.1:3334 tui --session ses_abc
```

部署服务器直接运行 `hypertrade tui`，wrapper 会使用短生命周期 TUI 镜像。页面左侧
是 Session/Task，中间是 Graph/Timeline，右侧是 Evidence；下方 tabs 显示 Task、
Experiment、Validation 和 Approval。80 列自动进入 compact 模式。

- `Ctrl+N`：聚焦多行新任务输入。
- `Ctrl+P`：请求暂停。
- `Ctrl+R`：根据服务端状态请求 resume 或 retry。
- `Ctrl+C`：请求取消任务，不是直接退出。
- `R`：重读 REST snapshot；`G/E/A`：切换图、证据和审批；`?`：帮助；`Q`：退出。

所有控制弹窗必须填写 reason。TUI 只提交 API 请求，不会绕过管理员认证、idempotency、
任务状态机、预算或风险门禁。SSE 断线时会从最后 sequence 对账；发现 sequence gap
会强制重读 Task snapshot。

#### 市场数据

```bash
/price ETH                      # 查看 ETH 价格
/candles ETH 1H 120            # 获取 ETH 1小时 K线（120根）
/compare ETH SOL BTC           # 比较多个币种的相对强度
```

或使用自然语言：
```bash
看下目前市场的热度怎么样
ETH 现在什么价格？
比较一下 BTC 和 ETH 最近的表现
```

#### 知识检索

```bash
/rag 风控                      # 在知识库中搜索风控相关内容
/memory search 市场             # 在 Memory 中搜索市场相关记录
```

### 命令历史

CLI 支持命令历史记录：
- **↑/↓ 方向键**：浏览命令历史
- **Ctrl+R**：反向搜索历史命令
- **Tab**：自动补全斜杠命令

### 颜色输出

在支持的终端中，CLI 会使用语义颜色：
- **绿色**：成功和确认
- **黄色**：警告和待批准项
- **红色**：错误
- **蓝色**：工具调用和类别
- **灰色**：次要信息

禁用颜色：
```bash
NO_COLOR=1 uv run ht --local
```

---

## Web 界面使用

访问 http://localhost:3333/harness 打开 Web 控制台。

### 主要功能区

1. **概览面板**：
   - 系统状态（提供者、工具、连接器）
   - 市场快照（涨跌幅榜、行情热度）
   - 最近的 Agent 运行
   - RAG 和 Memory 统计
   - 追踪事件

2. **Agent 运行**：
   - 创建新的 Agent 运行
   - 查看运行历史
   - 查看详细报告和追踪

3. **市场数据**：
   - 实时行情快照
   - K线图表
   - 币种比较工具

4. **策略实验室**：
   - 策略研究记录
   - 回测结果
   - 实验管理

5. **模拟盘控制**：
   - 模拟盘状态
   - 持仓查看
   - 暂停/恢复/重置控制

6. **实盘订单**：
   - 订单意图列表
   - 批准/拒绝界面
   - 执行状态追踪

### 认证

某些操作需要管理员认证：
1. 点击"登录"按钮
2. 输入管理员用户名和密码（在 `.env` 中配置）
3. 登录后可执行特权操作

---

## 市场研究工作流

### 查看市场概况

**CLI**：
```bash
看下目前市场的热度怎么样
```

**预期行为**：
- Agent 自动选择 `market_summary` 工具
- 报告包含：市场广度、上涨/下跌币种数、平均涨跌幅、最强/最弱币种、热门币种

### 查看单个币种

**CLI**：
```bash
/price BTC
ETH 现在什么价格？
```

**返回信息**：
- 当前价格
- 24小时涨跌幅
- 24小时成交量
- 资金费率
- 持仓量

### 技术分析

**CLI**：
```bash
/candles BTC 1H 120
分析一下 ETH 4小时级别的趋势
```

**返回信息**：
- OHLCV 数据
- 趋势特征（SMA、EMA、RSI 等）
- 支撑阻力位
- 趋势判断

### 多币种比较

**CLI**：
```bash
/compare BTC ETH SOL
比较一下 Layer1 币种的表现
```

**返回信息**：
- 相对强度排名
- 涨跌幅对比
- 成交量对比
- 资金流向

---

## 策略研究与回测

### 策略研究流程

HyperTrade 采用证据驱动的策略研究流程：

1. **创建研究记录** → 2. **运行回测** → 3. **比较变体** → 4. **记录知识** → 5. **规划下一步**

### 创建研究记录

**CLI**：
```bash
/research 研究ETH趋势突破策略
```

**API**：
```bash
curl -X POST http://localhost:3334/api/strategy/research \
  -H "Content-Type: application/json" \
  -d '{"prompt":"研究ETH趋势突破策略"}'
```

**返回**：
- 研究 ID
- 初始分析报告
- 建议的策略参数

### 运行回测

**CLI**：
```bash
/backtest
```

**Web**：在策略实验室中填写回测表单。

**回测参数**：
- `strategy_key`：策略标识（如 `momentum_breakout_v1`）
- `symbol`：交易币种（如 `BTC`、`ETH`）
- `bar`：时间级别（如 `1H`、`4H`）
- `candle_limit`：K线数量
- `initial_cash`：初始资金
- `candle_source`：数据源（`okx`、`bitpro`、`sample`）

**回测结果**：
- 总收益率
- 夏普比率
- 最大回撤
- 胜率
- 交易次数
- 权益曲线
- 交易明细

### 策略实验

**CLI**：
```bash
/experiment 实验ETH动量突破策略的不同参数
```

策略实验会自动运行三个变体：
- **基线（baseline）**：标准参数
- **快速（fast）**：更激进的参数
- **保守（conservative）**：更保守的参数

系统会：
1. 运行所有变体的回测
2. 比较结果
3. 通过门禁条件选择赢家
4. 生成策略知识 Memory
5. 建议下一个实验方向

### 策略库查询

**CLI**：
```bash
/strategy library momentum_breakout_v1
查看动量突破策略的历史证据
```

**返回**：
- 策略的所有证据记录
- 平均置信度
- 标签汇总
- 最新实验结果
- 改进建议

### 结构化研究证据

Evidence V2 把研究结论分为事实、推断、反证和数据缺口。操作员查看时应重点检查：

- `status` 是否仍为 `active`，以及 `as_of` / `valid_until` 是否覆盖当前决策窗口；
- Fact 是否至少有一个非 Memory 且 available 的 source；
- Inference 是否列出 active supporting evidence；
- `source_health` / `data_gaps` 是否表明原始 Trace、RAG 或 Memory 已失效；
- graph 中是否存在 `challenges`、`opposed_by` 或 `supersedes` 关系。

```bash
curl "http://localhost:3334/api/research/evidence?symbol=BTC&type=fact"
curl "http://localhost:3334/api/research/evidence/evi_abc123/graph?depth=2"
```

证据读取不需要把旧数据改写为新事实。旧实验和 Memory 会显示 `legacy=true`；Memory
只能作为上下文，不能单独证明市场事实。Append、expire、reject、supersede 只能由
已登录管理员通过受信 API 执行，Agent 没有直接修改证据的工具。置信度是研究声明，
不是盈利概率或收益保证。

---

## 模拟盘管理

### 查看模拟盘状态

**CLI**：
```bash
/paper
```

**Web**：在模拟盘控制面板查看。

**API**：
```bash
curl http://localhost:3334/api/paper/status
```

**状态信息**：
- 是否启用
- 是否运行中
- 当前权益
- 盈亏金额和百分比
- 持仓列表
- 每个持仓的盈亏

### 控制模拟盘

**CLI**：
```bash
/paper pause           # 暂停所有交易
/paper pause BTC       # 暂停 BTC 交易
/paper resume          # 恢复交易
/paper close           # 平掉所有仓位
/paper reset           # 重置模拟盘
```

**Web**：在模拟盘控制面板中点击相应按钮。

**API**：
```bash
curl -X POST http://localhost:3334/api/paper/control \
  -H "Content-Type: application/json" \
  -H "Cookie: hypertrade_session=<session_token>" \
  -d '{"action":"pause","symbol":"BTC"}'
```

**注意**：控制操作需要管理员认证。

---

## 实盘操作

### 订单意图流程

HyperTrade V1 支持 OKX Testnet 执行。实盘订单执行在 V1 中被阻止。

完整流程：
1. **创建订单意图** → 2. **审查意图** → 3. **批准意图** → 4. **风控检查** → 5. **执行订单**

### 创建订单意图

**CLI**：
```bash
/live intent ETH buy 0.01 reason="测试订单"
```

**API**：
```bash
curl -X POST http://localhost:3334/api/live/order-intents \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH",
    "side": "buy",
    "size": "0.01",
    "order_type": "market",
    "reason": "测试订单"
  }'
```

### 查看订单意图

**CLI**：
```bash
/live intents
```

**Web**：在实盘订单面板查看。

**API**：
```bash
curl http://localhost:3334/api/live/order-intents
```

### 批准订单意图

**CLI**：
```bash
/live approve loi_abc123
```

**Web**：在订单意图详情中点击"批准"。

**API**：
```bash
curl -X POST http://localhost:3334/api/live/order-intents/loi_abc123/approve \
  -H "Content-Type: application/json" \
  -H "Cookie: hypertrade_session=<session_token>" \
  -d '{"reason":"已审核通过"}'
```

### 拒绝订单意图

**CLI**：
```bash
/live reject loi_abc123 reason="风险过高"
```

**API**：
```bash
curl -X POST http://localhost:3334/api/live/order-intents/loi_abc123/reject \
  -H "Content-Type: application/json" \
  -H "Cookie: hypertrade_session=<session_token>" \
  -d '{"reason":"风险过高"}'
```

### 执行订单

**CLI**：
```bash
/live execute loi_abc123
```

**API**：
```bash
curl -X POST http://localhost:3334/api/live/order-intents/loi_abc123/execute \
  -H "Cookie: hypertrade_session=<session_token>"
```

**执行要求**：
- 订单意图已批准
- 通过风控检查
- 配置了 OKX Testnet 凭证
- 幂等性和可审计追踪

**注意**：主网执行在 V1 中被阻止。

---

## BitPro 集成

HyperTrade 通过 MCP 适配器与 BitPro 集成。所有 BitPro 操作都保持源边界可见。

### 配置 BitPro

在 `.env` 中配置：
```bash
BITPRO_MCP_API_BASE="http://your-bitpro-instance/api"
BITPRO_MCP_API_TOKEN="your-token"
BITPRO_MCP_AUTH_HEADER="X-Agent-Token"
```

### BitPro 工作流

每个 BitPro 流程都遵循：
```
bitpro_capabilities → bitpro_health → 最小必需的 BitPro 工具
```

### 查询 BitPro 回测

**CLI**：
```bash
查看 BitPro 回测收益大于100%的策略有哪些
```

**预期行为**：
- 调用 `bitpro_capabilities` 检查能力
- 调用 `bitpro_health` 检查健康状态
- 调用 BitPro 回测查询工具
- 使用 BitPro 的 `total_return_pct` 排名（不推断或年化）

### 查看回测详情

**CLI**：
```bash
查看 BitPro 回测 result 196 的权益曲线和交易证据
```

**返回**：
- 归一化的指标
- 有界的权益样本
- 交易/订单/成交样本
- 回撤数据
- 缺失字段标记为不可用

### 监控模拟盘

**CLI**：
```bash
监控 BitPro 所有运行中的模拟盘策略，列出异常和数据缺口
```

**返回**：
- 运行中的策略列表
- 告警
- 数据缺口
- 只读建议操作

**注意**：BitPro 监控是只读的。HyperTrade 不会推断缺失的 PnL、回撤或运行状态。

### 查询实盘信息

**CLI**：
```bash
我的实盘最近的一笔订单是什么
看下实盘收益最高的策略
```

**返回**：
- 实盘订单历史
- 实盘策略表现
- 持仓诊断

**注意**：这些是只读诊断工具。实盘写入工具在 V1 中被阻止。

---

## RAG 与 Memory

### RAG（检索增强生成）

RAG 用于从 `docs/knowledge` 中检索源支持的文档上下文。

**CLI 搜索**：
```bash
/rag 风控
/rag strategy research
```

**API 搜索**：
```bash
curl "http://localhost:3334/api/rag/search?query=风控&limit=5"
```

**返回**：
- 匹配的文档片段
- 源文件路径
- 相似度评分
- 上下文元数据

**用途**：
- 查询策略研究最佳实践
- 查找风控规则
- 检索部署文档
- 获取工具使用指南

### Memory

Memory 用于存储审计的运行时观察和策略证据。

**CLI 搜索**：
```bash
/memory search 市场
/memory search tag:strategy
```

**API 搜索**：
```bash
curl "http://localhost:3334/api/memory?query=市场&limit=10"
```

**Memory 类型**：
- `observation`：运行时观察
- `strategy_knowledge`：策略证据
- `market_context`：市场上下文

**Memory 字段**：
- `content`：内容
- `tags`：标签列表
- `confidence`：置信度（0-1）
- `importance`：重要性（0-1）
- `usage_count`：使用次数
- `disabled`：是否禁用

**删除 Memory**：
```bash
curl -X DELETE http://localhost:3334/api/memory/mem_abc123 \
  -H "Cookie: hypertrade_session=<session_token>"
```

---

## 监控与告警

### 监控器定义

**CLI 列出监控器**：
```bash
/monitors
```

**API 列出监控器**：
```bash
curl http://localhost:3334/api/monitors
```

**内置监控器**：
- `mon_bitpro_paper_all`：监控所有 BitPro 模拟盘策略
- `mon_strategy_library_freshness`：检查策略库更新
- `mon_connector_health`：检查连接器健康状态

### 手动运行监控

**CLI**：
```bash
/monitor run mon_bitpro_paper_all
```

**API**：
```bash
curl -X POST http://localhost:3334/api/monitors/mon_bitpro_paper_all/run
```

### 查看告警

**CLI**：
```bash
/alerts
```

**API**：
```bash
curl "http://localhost:3334/api/alerts?severity=warning&limit=25"
```

**告警级别**：
- `info`：信息
- `warning`：警告
- `critical`：严重

### 自动调度

监控器可以配置为自动运行：
```bash
MONITOR_SCHEDULER_ENABLED=true
MONITOR_LOOP_INTERVAL_SECONDS=300
```

**注意**：监控是只读的。它们不会调用模拟盘/实盘写入工具。

---

## 多 Agent 研究图

研究图是固定、受预算的 13 角色流程，不是动态创建的任意 Agent。查看拓扑、任务和
节点证据：

```text
/research-graph topology
/research-graph list
/research-graph show task_xxx
```

每个节点会显示 attempt、状态、预算使用和 Evidence V2 引用。缺少衍生品、事件源或
模型结构化输出时，系统记录 data gap；不会编造事实。重试仅重跑失败节点，已完成节点
和 evidence 会被复用。Strategy Engineer 只能生成严格 StrategySpec 并交给既有研究
编排队列，不能直接创建 BitPro 策略，也不能启动模拟盘或实盘。

创建和运行图使用管理员 API；生产 worker 会自动领取 queued 图任务。操作员可继续使用
通用 `/task <task_id> pause|resume|cancel|retry` 在安全点控制执行。

---

## 可复现实验账本

ResearchOrchestrator 在任何 BitPro 策略创建或回测写入前登记 fingerprint。相同语义输入的
queued/running/completed 实验复用一个 execution；失败重跑必须记录原因并追加新 attempt。

```text
/ledger list
/ledger show <fingerprint>
/ledger diff <left_fingerprint> <right_fingerprint>
```

`show` 查看 attempt、状态和 Evidence 数；`diff` 按策略、数据、成本、模型、prompt hash、
工具和 policy 解释变化。账本仅显示版本 hash、有界 metrics、BitPro refs、artifact hash 和
usage，不显示完整 prompt、凭据、private reasoning、原始 K 线或 raw result。

这证明实验可追溯，不证明策略盈利，也不会自动晋升模拟盘或实盘。

---

## 鲁棒性验证

研究编排会在受预算的参数矩阵后执行 locked OOS、walk-forward、邻域敏感性和成本压力；
有可靠市场状态窗口时才增加 regime 场景。查看结果：

```text
/validations list
/validations show <validation_id>
```

`validated` 表示所有 required hard gates 通过；`rejected` 表示至少一个 hard gate 失败；
`needs_data` 表示必需证据缺失；`needs_review` 表示需要人工判断。高收益但交易数不足、
样本外失败、参数尖峰或成本后失效的候选仍会被拒绝。只有 `validated` 证据才能申请人工
模拟盘晋升，查询或验证本身不会启动模拟盘，更不会触发实盘。

---

## 最佳实践

### 市场研究

1. **先宽后窄**：先查看市场概况，再深入单个币种
2. **多时间级别**：结合不同时间级别（1H、4H、1D）分析
3. **相对强度**：使用 `/compare` 发现强势币种
4. **追踪趋势**：定期运行市场监控，追踪市场变化

### 策略开发

1. **小步迭代**：从简单策略开始，逐步优化
2. **多变体测试**：使用 `/experiment` 测试不同参数组合
3. **记录证据**：每次实验都会自动生成策略知识 Memory
4. **查阅历史**：使用 `/strategy library` 查看历史证据
5. **门禁控制**：只推进通过门禁的策略到模拟盘

### 回测规范

1. **足够数据**：使用至少 100 根 K线
2. **真实数据**：优先使用 OKX 或 BitPro 真实数据
3. **交易成本**：考虑滑点和手续费
4. **样本外测试**：保留部分数据用于验证

### 模拟盘管理

1. **风险控制**：设置合理的初始资金和最大持仓
2. **定期检查**：使用 `/paper` 定期检查状态
3. **及时止损**：发现异常时使用 `/paper pause` 暂停
4. **清理重置**：测试完成后使用 `/paper reset` 重置

### 实盘操作

1. **小额测试**：首次使用小额测试
2. **Testnet 优先**：在 Testnet 充分测试后再考虑主网
3. **双重确认**：订单意图需要人工批准
4. **记录原因**：每个订单都要填写清晰的 `reason`
5. **监控执行**：执行后检查订单状态

---

## 常见问题

### 自由提示返回 `provider_unavailable`

**原因**：未配置聊天提供者密钥。

**解决**：
1. 检查 `DEEPSEEK_API_KEY` 或其他提供者密钥是否设置
2. 使用 `/model` 检查提供者状态
3. 使用确定性命令（如 `/price`、`/candles`）不需要提供者

### BitPro 工具返回 unavailable/502

**原因**：BitPro MCP 连接问题。

**解决**：
1. 检查 `BITPRO_MCP_API_BASE` 是否正确
2. 检查 `BITPRO_MCP_API_TOKEN` 是否有效
3. 访问 `/api/bitpro/health` 检查健康状态
4. 查看后端日志获取详细错误

### 市场数据为空

**原因**：Worker 未摄取数据或 OKX 不可用。

**解决**：
1. 检查 `/api/market/tickers/latest` 是否有数据
2. 查看 worker 日志
3. 检查 `OKX_REST_URL` 配置
4. 确认网络连接正常

### RAG 搜索无结果

**原因**：知识库未扫描或查询语料库为空。

**解决**：
1. 检查 `KNOWLEDGE_DIR` 配置
2. 确认 `docs/knowledge/` 目录有文档
3. 检查 RAG 扫描日志
4. 尝试更广泛的查询词

### Testnet 订单执行失败

**原因**：缺少 OKX Testnet 凭证或风控拒绝。

**解决**：
1. 检查订单意图状态
2. 查看风控负载
3. 确认 `OKX_TESTNET=true` 已设置
4. 检查 OKX API 密钥配置
5. 查看订单执行日志

### 部署成功但公开 UI 失败

**原因**：Nginx/前端/API 不匹配。

**解决**：
1. 检查 `curl :3333/api/health`
2. 运行 `docker compose ps` 查看服务状态
3. 检查 Nginx 配置
4. 查看容器日志

### CLI 命令历史不工作

**原因**：不在真实 TTY 中或使用旧版本。

**解决**：
1. 确保在真实终端中运行（不是管道或脚本）
2. 更新到最新版本
3. 检查 readline 库是否正常

### Web 界面加载慢

**原因**：首次启动或数据量大。

**解决**：
1. 等待初始数据加载完成
2. 清理旧的运行记录和追踪事件
3. 检查数据库性能
4. 考虑使用 PostgreSQL 代替 SQLite

---

## 获取帮助

- **文档**：查看 `docs/` 目录下的详细文档
- **架构**：查看 `docs/architecture/` 了解系统设计
- **运行手册**：查看 `docs/runbooks/` 了解操作程序
- **合约**：查看 `docs/contracts/` 了解功能范围
- **问题报告**：通过仓库提交 Issue

---

## 下一步

- 阅读 [开发者指南](developer-guide.md) 了解如何扩展 HyperTrade
- 阅读 [API 参考](api-reference.md) 了解完整的 API 文档
- 查看 [架构文档](architecture/) 了解系统设计
- 浏览 [知识库](knowledge/) 学习最佳实践
