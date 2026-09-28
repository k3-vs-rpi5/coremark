[English](README.md)

# CoreMark 项目

本仓库是完整的 CoreMark 评测与优化项目，不保存报告或原始证据。同步工作区中的
foundation 仓库负责设备准入，独立 reports 仓库负责审阅封存证据。

## 固定对比契约

每份报告必须分开保留三条轨道：树莓派 5 4 GB 原生 Debian 13
（`rpi-native`）、K3 Pico 使用锁定 Debian 13 riscv64 rootfs
（`k3-compatible`），以及 K3 Pico 原生 Bianbu 4.0.4
（`k3-development`）。每条轨道分别保留 `default-parity` 和
`best-achievable`；K3 优化分数绝不能替换统一参数的默认分数。

准确源码、环境 profile digest、GCC 版本和 K3 Clang 23 软件包身份记录在
`sources.lock.yaml` 与 `environments.lock.yaml`。缺少的编译链只能通过 APT
安装。SD 与 UFS 访问排除在计时外；Type-C 供电和有线网络由 foundation 控制。

## 公开接口

面向操作者的脚本严格只有两个：

```sh
scripts/build.sh --work-root /absolute/new/build \
  --track rpi-native --result-mode default-parity

scripts/run.sh --work-root /absolute/build \
  --evidence-root /absolute/evidence \
  --track rpi-native --result-mode default-parity \
  --runtime-profile-digest <locked-foundation-profile-sha256> --formal
```

`build.sh` 自动拉取固定官方源码、执行 `make check`、按需应用 manifest 排序的
零 fuzz 补丁、构建两种官方模式、反向恢复补丁、证明源码树干净并封存构建。
`run.sh` 验证构建闭包，先跑官方正确性，再执行 3 次预热，之后进行性能采样，
并逐样本记录频率和温度。quick 结果永不可发布；formal 结果为 3 轮 × 30 个保留
样本，完成独立审阅前仍不得公开。

K3-compatible 构建和运行必须将 `COREMARK_ROOTFS` 指向规范化的锁定 rootfs。
K3 best-achievable 构建还要通过 `--compiler-artifact` 和 `--packages-index`
提供锁定 APT 软件包与索引。两个脚本的完整参数可用 `--help` 查看。输出必须是
本仓库外的新绝对路径；失败运行也会作为 checksum 封存的 invalid 证据保留。

## K3 best-achievable 通道

工作区的交叉工具链是 spacemit GCC 工具链，且各 parity 轨道保留各自锁定的编译器。
`k3-development` 的 best-achievable 通道可以额外使用 `environments.lock.yaml`
中记录的、经评审的 Clang 通道：

```sh
scripts/build.sh --work-root /absolute/new/build \
  --track k3-development --result-mode best-achievable \
  --compiler-kind clang23-pgo
```

该通道使用锁定的 Clang 23 主机软件包、spacemit sysroot、`-mcpu=spacemit-x100`
以及板上生成的 LLVM profile 进行交叉编译。当编译器、riscv64 profile runtime 或
profile 数据与其记录的 SHA256 不一致时直接失败关闭。在 K3 Pico ITX 上该通道实测
约 8.6 CoreMark/MHz，而 GCC 通道约 7.6 CoreMark/MHz，因此该通道产出的结果标记
为 best-achievable，绝不替换同参数的默认结果。

## 优化和补丁状态

`patches/` 中接受的系列只新增可选的 X100 `core_portme.mak`，受 checksum 控制的
工作负载文件没有变化。本地保留的 K3 正式结果使用 Clang 23.0.0git 达到
8.323516 CoreMark/MHz，超过 7.7 技术目标。这只是历史本地证据，不是公开声明；
新的工作区 release 必须重新复现，并在 reports 仓库完成独立审阅。

测试特意保持精简，只覆盖契约：

```sh
PYTHONPATH=src python3 -m pytest tests -q
ruff check src tests
sh -n scripts/build.sh scripts/run.sh
shellcheck scripts/build.sh scripts/run.sh
```
