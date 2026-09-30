# 实施方案

在各仓库隔离工作区执行。HyperTrade 实现独立的外部命名协议校验并接入两处创建入口；BitPro 只收紧既有数值审计。新增失败回归、验证兼容名称和小数资金。先做 GitNexus impact，提交前 detect-changes；同步既有规格、合同与进度。HyperTrade 完整 check.sh，BitPro 定向回归及构建/静态检查；PR 合并后分别记录部署触发/结果。
