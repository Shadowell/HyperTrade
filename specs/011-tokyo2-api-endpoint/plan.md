# 实施方案：HyperTrade 东京新机默认连接地址

**日期**：2026-09-24
**规格**：[spec.md](spec.md)

## 方案

更新 `backend/src/hypertrade/cli.py` 与 `desktop/src/bridge.ts` 的默认地址。桌面端提供纯函数识别旧默认 URL，`App.tsx` 初始化时使用它；自定义地址不变。新增桌面端单测并同步现有 CLI 远程显示用例。更新产品规格、冲刺合同和进度。

## 验证

先运行定向 Python 与 Vitest，再运行 `./scripts/check.sh`；GitNexus 在编辑前分析常量及 `App`，提交前运行 `detect_changes()`。本分支完成后在服务器迁移切换阶段才落到 `main`，避免旧机自动部署。

## 风险

桌面端持久化值可能为旧 IP；只迁移精确匹配的旧默认值，避免覆盖用户自定义服务器。旧机在目标 API 验收前保持可回退。
