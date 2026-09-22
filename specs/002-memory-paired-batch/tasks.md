# Tasks: 多任务记忆配对评测

- [x] T001 [US1] 在 `tests/test_memory_ablation_batch.py` 写冻结矩阵、漂移、篡改回归。
- [x] T002 [US1] 在 `backend/src/hypertrade/evals/memory_ablation_batch.py` 实现有序、内容寻址矩阵创建。
- [x] T003 [US2] 写跨进程恢复及缓存重建回归；实现仅运行未结算 pair 的批量入口。
- [x] T004 [US3] 为单 pair 摘要补开发实验分母，并实现按臂成功率、失败分类、调用量和重复率汇总。
- [x] T005 [US3] 验证未知/缺失证据不被伪造，定向 pytest、Ruff、mypy；独占窗口跑完整检查。
- [x] T006 完成 GitNexus 影响与变更检查、scope review，在任务分支提交并回报总控。
