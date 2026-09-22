# Tasks: SQLite 内存会话串行化

- [x] T001 写事件屏障双线程红测，证明同一 StaticPool 连接会并发进入 session。
- [x] T002 在 Database 实例内为 SQLite 内存 StaticPool 建立 RLock，覆盖 session 创建至 close。
- [x] T003 补异常后释放、跨实例独立与文件 SQLite 不加锁测试。
- [x] T004 跑定向 pytest、Ruff、mypy 与 GitNexus detect_changes，审查后本地提交并回报总控。
