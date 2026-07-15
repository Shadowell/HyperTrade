# User-directed contract — Desktop Floating Mission Bot

> 状态：Local implementation complete — 2026-07-16。该工作由用户明确扩展，不改变 Sprint 116
> Gate M，也不声称已发布到生产下载渠道。

## Goal

提供一个不依赖浏览器页面的 macOS 桌面悬浮入口：平时以小图标置顶，展开后连接 HyperTrade
Mission Runtime，呈现简洁、可验证、左右分明的研究对话。

## In scope

- Tauri 2 原生壳、透明置顶窗口、屏幕右下角锚定、拖动、收起、隐藏与托盘菜单。
- React/TypeScript 对话面板和 Mission 公共 SSE 事件投影。
- Rust 侧服务健康检查和 SSE 代理，WebView 不直接持有服务或交易凭据。
- 用户消息靠右、HT 结论靠左；原创非人物产品图标，小尺寸仍清晰。
- macOS `.app` 本地构建、前端与 Rust 测试、Retina 逻辑尺寸验证。

## Out of scope

- 浏览器内悬浮组件或修改 `/harness`。
- Claude Code 类完整 IDE、终端或文件编辑器。
- 本地模型、交易密钥、paper/live/order/capital mutation。
- 自动更新、公证、Developer ID 签名、DMG 或 App Store 发布。

## Done means

- 收起态为 64×64 逻辑像素，产品主体不超过 52px；展开态为 420×640 逻辑像素。
- 一轮对话中用户问题显示在右侧，HT 欢迎语、流式结论、证据和错误显示在左侧。
- 桌面端消费 `answer_delta`、`evidence_ready`、`warning`、`final` 和错误事件，不复制
  Mission 状态机或交易业务逻辑。
- `pnpm check`、Tauri app bundle 构建和 `git diff --check` 通过。

## Verification

```bash
cd desktop
pnpm check
pnpm tauri build --bundles app
codesign --verify --deep --strict src-tauri/target/release/bundle/macos/HyperTrade\ Bot.app
```
