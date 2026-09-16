[English](AGENTS.md)

# CoreMark 项目要求

本文件是 CoreMark 的项目级契约，用于收紧（绝不放宽）工作区根 `AGENTS.md` 与
governance 文档中的协作契约，只记录 CoreMark 特有的内容。

- 交叉编译默认使用工作区工具链 `spacemit-toolchain-linux-glibc-x86_64-v1.2.2/`
  及其自带的 `sysroot/`。
- 固定版本的上游源码是本地检出 `src/coremark`，提交为
  `b56889a7bd9d5624fbeff2a73ba69878e6a9c146`，完整性命令为 `make check`，
  工作负载文件受 `coremark.md5` 控制。
- 固化的自动化在 `src/coremark_project`，只通过 `scripts/build.sh` 与
  `scripts/run.sh` 对外提供。
- 被接受的优化固化为 `patches/` 中顺序编号的 `coremark-k3-x100` 系列，附带
  `manifest.yaml` 登记项与中英文说明；上游检出处没有落地位置的编译参数类优化
  落在 `src/coremark_project`。
- 设备交付、执行与分析遵循 governance 流程，通过工作区凭据 `.ssh-k3` 与
  `.ssh-rpi`，证据封存在所有受管 Git 仓库之外。
