[English](AGENTS.md)

# CoreMark 项目操作要求

本文件是 CoreMark 的项目级契约，用于收紧（绝不放宽）工作区根 `AGENTS.md`、
governance 文档和 `project.yaml` 中的协作契约。CoreMark 的工作要求记录在
`AGENTS.md` / `AGENTS.zh-CN.md` 这一对文件中，两份文件内容一致。

## 统一交叉编译链

凡是需要在板子上执行的交叉编译产物，统一使用工作区内的
`spacemit-toolchain-linux-glibc-x86_64-v1.2.2/` 工具链构建，例如
`bin/riscv64-unknown-linux-gnu-gcc`（GCC 15.2.0）及其自带的 `sysroot/`。
不得改用宿主机编译器、其它交叉工具链或未声明的厂商软件包。编译器、链接器、
binutils、libc、sysroot 版本以及编译器可执行文件 SHA-256 必须写入构建清单和
封存证据。

若某条轨道无法用该工具链构建，则只能按 `environments.lock.yaml` 中锁定的环境
执行，并作为经人工批准的显式偏差声明；受影响的结果必须标注为偏差，绝不能作为
`default-parity` 呈现。

## 向目标设备交付并运行

交叉编译成果按“主机推送”的方式交付到目标板，在板子上运行并分析：

- 目标地址、账号和认证信息只来自工作区本地凭据文件 `.ssh-k3`（K3 Pico）与
  `.ssh-rpi`（树莓派 5）；AI 贡献者只检查它们是否存在、路径、属主和 `0600`
  权限位，绝不读取、打印、提交、上传或复制凭据值；
- 由主机把选定的构建输入推送到板子，并在板子上执行项目脚本；不得让板子自行
  clone、pull、download 或以其它方式独立选择代码；
- 采集并分析运行的原始输出、遥测和日志，运行结果封存在所有受管 Git 仓库之外
  的显式绝对证据根目录下；失败或中断的运行保留为 `invalid` 或 `blocked`。

## 源码布局与脚本固化

CoreMark 项目保持 `src/coremark` / `src/coremark_project` 布局：

- `src/coremark` 是固定版本上游仓库的本地检出（`sources.lock.yaml` 中的提交
  `b56889a7bd9d5624fbeff2a73ba69878e6a9c146`，完整性命令 `make check`，受
  checksum 控制的 `coremark.md5` 工作负载文件）。它解决 “git 下载必须定版”
  的问题，也是唯一进行源码优化编辑的位置。
- `src/coremark_project` 是把操作固化下来的 Python 包，覆盖源码获取、构建、
  交付、运行、遥测与证据，使项目对外仍然只有 `scripts/build.sh` 与
  `scripts/run.sh` 两个公开入口。

新增操作先在 `src/coremark_project` 中实现，并通过这两个脚本对外提供；临时的
shell 流水线不构成交付。

## 优化落地

优化在本地检出 `src/coremark` 中编辑、构建和测量。优化被接受后，才固化到 Git
仓库并记录：`patches/` 中顺序编号、零 fuzz、可回退的补丁，并附带
`manifest.yaml` 登记项与中英文说明。当项目工作区没有编译参数类优化的落地位置
时，该类优化改在 `src/coremark_project` 中落地。

绝大多数优化应落在源码中，而不是编译参数上。仅改参数或开关属于例外，且每一次
都必须说明其假设、单变量实验和实测效果。
