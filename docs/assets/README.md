# HyperTrade 视觉资源

本目录包含 HyperTrade 项目的视觉资源。

## Logo

- **logo.svg** - 主 Logo（SVG 矢量格式）
- **logo.png** - Logo PNG 版本（待生成）
- **logo-dark.svg** - 深色背景 Logo（待生成）

## 截图

截图展示 HyperTrade 的核心功能：

### Web 控制台
- **screenshot-harness-overview.png** - 控制台概览页面
- **screenshot-agent-run.png** - Agent 运行详情
- **screenshot-market-view.png** - 市场数据视图
- **screenshot-strategy-lab.png** - 策略实验室

### CLI
- **screenshot-cli-market.png** - CLI 市场查询
- **screenshot-cli-strategy.png** - CLI 策略操作

## 架构图

- **hypertrade-architecture.svg** - 系统架构图
- **agent-runtime-flow.svg** - Agent 运行时流程图
- **data-flow-diagram.svg** - 数据流图

## GIF 演示

- **demo-quick-start.gif** - 快速开始演示
- **demo-strategy-research.gif** - 策略研究流程
- **demo-paper-trading.gif** - 模拟盘操作

## 使用指南

在文档中引用这些资源：

```markdown
![HyperTrade Logo](docs/assets/logo.svg)
![控制台概览](docs/assets/screenshot-harness-overview.png)
```

## 生成说明

### 截图
1. 启动本地 HyperTrade 实例
2. 访问 http://localhost:3333/harness
3. 使用截图工具捕获关键功能页面
4. 保存为 PNG 格式，分辨率 1920x1080

### GIF 演示
1. 使用 LICEcap 或 Kap 录制屏幕
2. 保持帧率 15-20 FPS
3. 限制文件大小 < 5MB
4. 添加文字说明标注关键步骤

### Logo 变体
如需生成 PNG 版本：
```bash
# 使用 Inkscape 或在线工具转换
inkscape logo.svg --export-type=png --export-width=512 -o logo.png
```

## 版权

所有视觉资源归 HyperTrade 项目所有。
