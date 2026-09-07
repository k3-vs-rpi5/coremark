[中文](README.zh-CN.md)

# CoreMark project

This repository is the complete CoreMark benchmark and optimization project. It
does not own reports or raw evidence. A synchronized foundation repository
qualifies the devices; the separate reports repository reviews sealed evidence.

## Fixed comparison contract

Every report keeps three tracks separate: Raspberry Pi 5 4 GB on native Debian
13 (`rpi-native`), K3 Pico in the locked Debian 13 riscv64 rootfs
(`k3-compatible`), and K3 Pico on native Bianbu 4.0.4 (`k3-development`). Each
track retains both `default-parity` and `best-achievable`; an optimized K3 score
never replaces the equal-parameter default score.

The exact source, environment-profile digests, GCC versions, and the K3 Clang
23 package are in `sources.lock.yaml` and `environments.lock.yaml`. Missing
toolchains are installed through APT only. SD and UFS access are excluded from
timing; Type-C power and wired Ethernet are controlled by the foundation.

## Public interface

There are exactly two operator scripts:

```sh
scripts/build.sh --work-root /absolute/new/build \
  --track rpi-native --result-mode default-parity

scripts/run.sh --work-root /absolute/build \
  --evidence-root /absolute/evidence \
  --track rpi-native --result-mode default-parity \
  --runtime-profile-digest <locked-foundation-profile-sha256> --formal
```

`build.sh` fetches the pinned official source, runs `make check`, optionally
applies the manifest-ordered zero-fuzz patch, builds both official modes,
reverses the patch, proves a clean tree, and seals the build. `run.sh` verifies
the build closure, runs official correctness first, performs three warmups, then
runs performance samples with per-sample frequency and temperature telemetry.
Quick runs are never reportable. Formal runs are 3 sessions × 30 retained
samples and remain non-public until independent review.

For K3-compatible builds and runs, set `COREMARK_ROOTFS` to the canonical locked
rootfs. For best-achievable K3 builds, provide the locked APT package and package
index with `--compiler-artifact` and `--packages-index`. Use `--help` on either
script for the complete interface. Outputs must be new absolute paths outside
this repository; failed runs are retained as checksum-sealed invalid evidence.

## Optimization and patch status

The accepted series in `patches/` adds only an opt-in X100 `core_portme.mak`;
checksum-controlled workload files remain unchanged. The locally retained K3
formal result reached 8.323516 CoreMark/MHz with Clang 23.0.0git, above the 7.7
technical target. This is historical local evidence, not a public claim; a new
workspace release must reproduce it and receive independent review in the
reports repository.

Tests are deliberately small and contract-focused:

```sh
PYTHONPATH=src python3 -m pytest tests -q
ruff check src tests
sh -n scripts/build.sh scripts/run.sh
shellcheck scripts/build.sh scripts/run.sh
```
