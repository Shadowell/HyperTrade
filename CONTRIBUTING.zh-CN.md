# 为 HyperTrade 做贡献

感谢您对 HyperTrade 的关注！本文档提供了为项目做贡献的指南和说明。

## 目录

- [行为准则](#行为准则)
- [快速开始](#快速开始)
- [开发工作流](#开发工作流)
- [代码规范](#代码规范)
- [测试](#测试)
- [文档](#文档)
- [提交变更](#提交变更)
- [审核流程](#审核流程)

---

## 行为准则

本项目遵守行为准则。参与即表示您同意遵守此准则。请向项目维护者报告不可接受的行为。

### 我们的标准

**积极行为**：
- 使用欢迎和包容的语言
- 尊重不同的观点和经验
- 优雅地接受建设性批评
- 专注于对社区最有利的事情
- 对其他社区成员表现出同理心

**不可接受的行为**：
- 挑衅、侮辱性或贬损性评论，以及人身或政治攻击
- 公开或私下骚扰
- 未经明确许可发布他人的私人信息
- 在专业环境中可能被合理视为不当的其他行为

---

## 快速开始

### 前置条件

- Python 3.12+
- `uv` 包管理器
- Node.js 18+ 和 `pnpm`
- Git
- Docker 和 Docker Compose（可选，用于 PostgreSQL）

### 设置开发环境

1. **Fork 并克隆**：
   ```bash
   git clone git@github.com:YOUR_USERNAME/HyperTrade.git
   cd HyperTrade
   ```

2. **设置 Python 环境**：
   ```bash
   uv sync
   ```

3. **设置前端**：
   ```bash
   npm exec --yes pnpm@10 -- -C frontend install
   ```

4. **配置环境**：
   ```bash
   cp .env.example .env
   # 编辑 .env，填入您的 API 密钥和配置
   ```

5. **初始化数据库**：
   ```bash
   # SQLite（快速启动）
   mkdir -p .local
   export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"

   # PostgreSQL（推荐用于开发）
   docker compose up -d postgres
   export DATABASE_URL="postgresql://hypertrade:hypertrade@localhost:5432/hypertrade"
   uv run alembic upgrade head
   ```

6. **验证设置**：
   ```bash
   ./scripts/check.sh
   ```

---

## 开发工作流

### 分支策略

**当前工作流**：直接提交到 `main` 分支。

未来贡献：
- 从 `main` 创建功能分支：`git checkout -b feature/your-feature-name`
- 使用描述性分支名称：`feature/`、`bugfix/`、`docs/`、`refactor/`

### Sprint 合约

HyperTrade 开发按 Sprint 合约组织，位于 `docs/contracts/`。

**开始工作前**：
1. 检查 `docs/contracts/` 中的活动 Sprint 范围
2. 查看 `docs/architecture/` 中的相关架构文档
3. 了解验收标准和边界

**开发期间**：
- 将变更保持在当前 Sprint 合约范围内，除非明确扩展
- 引入新模式或组件时更新架构文档
- 添加评估用例以防止回归

### 进行变更

1. **创建分支**（未来工作流）：
   ```bash
   git checkout -b feature/add-new-tool
   ```

2. **进行变更**：
   - 编写清晰、可读的代码
   - 遵循代码规范（见下文）
   - 为新功能添加测试
   - 更新文档

3. **测试变更**：
   ```bash
   ./scripts/check.sh
   ```

4. **提交变更**：
   ```bash
   git add .
   git commit -m "添加新的市场情报工具"
   ```

   **提交消息格式**：
   ```
   简短摘要（50 字符以内）

   如有必要，提供更详细的解释性文本。换行约为 72 字符。
   将摘要与正文分隔的空行至关重要。

   - 使用项目符号可以
   - 使用现在时："添加功能"而不是"已添加功能"
   - 引用问题："修复 #123"或"相关 #456"
   ```

---

## 代码规范

### Python

**风格**：
- 遵循 PEP 8
- 为函数签名使用类型提示
- 最大行长度：100 字符

**格式化**：
```bash
uv run ruff format .
```

**检查**：
```bash
uv run ruff check .
```

**类型检查**：
```bash
uv run mypy backend/src
```

**示例**：
```python
from typing import Any

def get_market_ticker(
    symbol: str,
    include_funding: bool = True,
) -> dict[str, Any]:
    """获取币种的市场行情。
    
    Args:
        symbol: 币种名称（如 "BTC"、"ETH"）
        include_funding: 包含资金费率数据
        
    Returns:
        行情数据字典
    """
    # 实现
    pass
```

### TypeScript/React

**风格**：
- 所有新代码使用 TypeScript
- 遵循 ESLint 规则
- 使用带 Hooks 的函数式组件

**检查**：
```bash
npm exec --yes pnpm@10 -- -C frontend lint
```

**示例**：
```typescript
interface MarketTickerProps {
  symbol: string;
  onUpdate?: (data: TickerData) => void;
}

export function MarketTicker({ symbol, onUpdate }: MarketTickerProps) {
  const [data, setData] = useState<TickerData | null>(null);
  
  useEffect(() => {
    // 实现
  }, [symbol]);
  
  return (
    <div className="market-ticker">
      {/* 组件 JSX */}
    </div>
  );
}
```

### 文档

**代码注释**：
- 编写具有清晰变量和函数名称的自文档化代码
- 仅在代码无法清楚表达意图时添加注释
- 记录复杂算法或业务逻辑
- 保持注释与代码变更同步

**文档字符串**：
- 为所有公共函数、类和模块使用文档字符串
- Python 文档字符串遵循 Google 风格
- 在有用时包含类型信息和示例

---

## 测试

### 运行测试

**完整测试套件**：
```bash
./scripts/check.sh
```

**后端测试**：
```bash
uv run pytest tests/ -v
```

**前端测试**：
```bash
npm exec --yes pnpm@10 -- -C frontend test
```

**特定测试**：
```bash
uv run pytest tests/test_agent_eval_suite.py::test_eval_tool_choice -v
```

**带覆盖率**：
```bash
uv run pytest --cov=hypertrade --cov-report=html
```

### 编写测试

**测试结构**：
- 将测试放在 `tests/` 目录中
- 测试文件命名为 `test_*.py`
- 测试函数命名为 `test_*`
- 使用解释场景的描述性测试名称

**示例测试**：
```python
def test_market_ticker_returns_valid_data():
    """测试市场行情返回有效的行情数据。"""
    repo = MarketRepository(db)
    ticker = repo.get_ticker("BTC-USDT-SWAP")
    
    assert ticker is not None
    assert ticker.inst_id == "BTC-USDT-SWAP"
    assert ticker.last > 0
    assert ticker.volume_ccy_24h >= 0
```

### 评估用例

向 `AgentEvalSuite` 添加评估用例以防止回归：

```python
def _eval_my_new_feature(self) -> EvalResult:
    """测试我的新功能行为。"""
    kernel = AgentKernel(self.db, "docs/knowledge", self.settings)
    run = kernel.run_chat("测试我的新功能的提示")
    
    assert run.status == "completed"
    assert "expected_tool" in [t["tool"] for t in run.trace]
    
    return EvalResult(
        eval_id="my_new_feature",
        status="pass",
        message="功能正常工作"
    )
```

---

## 文档

### 何时编写文档

**始终记录**：
- 新工具、提供者或连接器
- API 更改或新端点
- 架构决策
- 配置更改
- 操作程序

**不要记录**：
- 代码中可见的实现细节
- 临时解决方法
- 调试笔记或聊天历史

### 文档类型

**架构文档**（`docs/architecture/`）：
- 模块级设计决策
- 组件交互
- 技术模式

**知识库**（`docs/knowledge/`）：
- 操作员指南
- 最佳实践
- 工具使用示例

**运行手册**（`docs/runbooks/`）：
- 部署程序
- 故障排除指南
- 事件响应

**合约**（`docs/contracts/`）：
- Sprint 范围和交付物
- 验收标准
- 技术规格

### 文档标准

- 用清晰简洁的中文或英文编写
- 使用 Markdown 格式
- 在有用时包含代码示例
- 保持文档与代码变更同步
- 链接相关文档

---

## 提交变更

### 提交前

- [ ] 代码遵循项目风格指南
- [ ] 所有测试通过（`./scripts/check.sh`）
- [ ] 为新功能添加了新测试
- [ ] 文档已更新
- [ ] 如需要添加了评估用例
- [ ] 提交消息清晰描述性

### 提交流程

**当前工作流**（直接到 main）：
1. 确保您的变更已提交
2. 推送到 `origin/main`
3. 通过 GitHub Actions 自动部署

**未来工作流**（使用 PR）：
1. 将您的分支推送到您的 fork
2. 针对 `main` 创建 Pull Request
3. 填写 PR 模板
4. 等待审核并处理反馈
5. 批准后，变更将被合并

### Pull Request 模板

```markdown
## 描述
变更的简要描述

## 变更类型
- [ ] Bug 修复
- [ ] 新功能
- [ ] 破坏性变更
- [ ] 文档更新

## 测试
- [ ] 所有测试通过
- [ ] 添加了新测试
- [ ] 手动测试

## 检查清单
- [ ] 代码遵循风格指南
- [ ] 文档已更新
- [ ] 无破坏性变更（或已记录）
- [ ] 遵守 Sprint 合约范围

## 相关 Issue
修复 #123
相关 #456
```

---

## 审核流程

### 审核标准

**代码质量**：
- 遵循项目约定
- 清晰且可维护
- 经过适当测试
- 没有不必要的复杂性

**功能性**：
- 满足要求
- 处理边缘情况
- 无回归
- 在 Sprint 范围内

**文档**：
- 架构文档已更新
- API 更改已记录
- 提供了使用示例

### 响应时间

- 审核通常在 1-2 个工作日内
- 及时处理反馈
- 保持耐心和尊重

### 批准后

- 变更将被合并到 `main`
- 自动部署到生产环境
- 监控部署日志
- 验证生产健康状态

---

## 获取帮助

### 资源

- **文档**：[docs/documentation-index.md](docs/documentation-index.md)
- **架构**：[docs/architecture/](docs/architecture/)
- **开发者指南**：[docs/developer-guide.zh-CN.md](docs/developer-guide.zh-CN.md)

### 沟通

- **Issues**：使用 GitHub Issues 报告错误和功能请求
- **Discussions**：使用 GitHub Discussions 提问
- **Email**：联系维护者处理敏感问题

---

## 许可证

通过为 HyperTrade 做贡献，您同意您的贡献将在与项目相同的许可证下授权。

---

## 认可

贡献者将在以下位置获得认可：
- 发布说明
- CHANGELOG.md
- 项目 README（如果是重大贡献）

感谢您为 HyperTrade 做贡献！🎉
