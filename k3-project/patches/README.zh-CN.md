[English](README.md)

# CoreMark 补丁规范

本目录只包含一个接受的公开补丁系列。诊断和被拒绝实验不作为公开补丁文件保留。

## 接受系列

唯一补丁为
[`0001-ports-add-linux-clang-port-for-spacemit-x100.patch`](0001-ports-add-linux-clang-port-for-spacemit-x100.patch)。
它只新增 `linux-spacemit-x100/core_portme.mak`；受 checksum 控制的 CoreMark
工作负载文件保持不变。

该补丁面向官方源码提交
`b56889a7bd9d5624fbeff2a73ba69878e6a9c146`，SHA256 为
`1ef3ac808aac18e43c3a8de5b60a9bace8ed1c90e4347f152ffcc2d58e493927`，
分类为 `upstream-ready-not-submitted`。

## 应用契约

`manifest.yaml` 是顺序和身份的权威来源。公开构建必须：

1. 应用系列前通过官方 `make check`；
2. 验证补丁 digest，并使用 `--fuzz=0` 应用；
3. 应用后通过官方 `make check`；
4. 使用声明的编译器与参数完成构建和验证；
5. 使用 `--fuzz=0` 反向恢复，通过 `make check` 并留下干净源码树。

## 被拒绝工作

早期工作负载源码和编译器 workaround 诊断没有进入 official-score 轨道。其机制与
结论归入独立 reports 仓库的 CoreMark 报告；详细本地文件仍可从迁移前 recovery
bundle 中恢复。
