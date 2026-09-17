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
- **待重新裁决，需人工批准。** `k3-compatible` 与 `k3-development` 两条运行时
  profile 固定的 foundation profile 摘要早于 foundation 提交 `306630b`——该提交把
  `config/runtime-profiles/k3-compatible-debian13.yaml` 与
  `config/runtime-profiles/k3-development-bianbu404.yaml` 中的工作频率从 `2200 MHz`
  修正为 `2000 MHz`。锁里仍记录修订前的摘要
  （`61c40d03e873625d3aa44fc8aa37642f96bbfce9d4334c3d8323cdcfa646f1a4` 与
  `62218ec3b29f5a1f33397393826270287d2c5e0fc1b96854f05d8a13d9d32328`），因此运行
  门禁会接受一个描述「已不存在的平台声明」的摘要。更新这两处 pin 属于环境锁变更，
  等待批准；当前摘要为
  `484e181fffbfa493dceee66588ef79a05f1cb2bbe95a7452d537bcfca1667214` 与
  `36357713156c805b464642b4f07c4dbbcc12bc7298856bf3934d1ee3d9f5b8ec`。
