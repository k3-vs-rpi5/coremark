[中文](AGENTS.zh-CN.md)

# CoreMark project operating requirements

This project-local contract narrows, and never relaxes, the workspace
collaboration contract in the root `AGENTS.md`, the governance documents, and
`project.yaml`. The CoreMark working requirements are recorded in the pair
`AGENTS.md` / `AGENTS.zh-CN.md`; both files carry the same content.

## One cross-compilation toolchain

Every cross build of a binary that is executed on a board uses the workspace
toolchain `spacemit-toolchain-linux-glibc-x86_64-v1.2.2/`, for example
`bin/riscv64-unknown-linux-gnu-gcc` (GCC 15.2.0) with the toolchain's own
`sysroot/`. A host compiler, a second cross toolchain, or an undeclared vendor
package is not substituted. Compiler, linker, binutils, libc, and sysroot
versions plus the compiler executable SHA-256 enter the build manifest and the
sealed evidence.

A track that cannot be built with this toolchain keeps its locked environment
from `environments.lock.yaml` only as a human-approved declared deviation. The
affected result is labelled as a deviation and is never presented as
`default-parity`.

## Delivery and execution on the target device

Cross-compiled results are delivered to the target board, executed there, and
analysed, following host-to-device delivery:

- target address, account, and authentication come only from the local-only
  workspace credential files `.ssh-k3` (K3 Pico) and `.ssh-rpi`
  (Raspberry Pi 5); the AI contributor checks existence, path, ownership, and
  mode `0600` only, and never reads, prints, commits, uploads, or copies the
  credential values;
- the host pushes the selected build inputs to the board and runs the project
  scripts there; the board never clones, pulls, downloads, or otherwise selects
  code itself;
- raw output, telemetry, and logs of the run are collected and analysed, and the
  run is sealed beneath an explicit absolute evidence root outside every managed
  Git repository. A failed or interrupted run stays `invalid` or `blocked`.

## Source layout and script solidification

The CoreMark project keeps the `src/coremark` / `src/coremark_project` layout:

- `src/coremark` is a local checkout of the pinned upstream repository (commit
  `b56889a7bd9d5624fbeff2a73ba69878e6a9c146` in `sources.lock.yaml`, integrity
  command `make check`, `coremark.md5`-controlled workload files). It solves the
  problem that a git download must be version-pinned, and it is the only place
  where source optimization is edited.
- `src/coremark_project` is the Python package that solidifies the operations —
  source retrieval, build, delivery, execution, telemetry, and evidence — so
  that the project still exposes exactly `scripts/build.sh` and
  `scripts/run.sh` as its public interface.

A new operation is first implemented in `src/coremark_project` and reached
through those two scripts; an ad-hoc shell pipeline is not a delivery.

## Optimization landing

Optimization is edited, built, and measured in the local checkout
`src/coremark`. Only after the change is accepted is it frozen into the Git
repository and recorded: an ordered, zero-fuzz, reversible patch in `patches/`
with its `manifest.yaml` entry and its bilingual note. When the project
workspace has no landing place for a compile-parameter-type optimization, that
optimization lands in `src/coremark_project` instead.

Most optimizations belong in the source code, not in compile parameters. A
flag-only or option-only change is the exception, and each one states its
hypothesis, its one-variable experiment, and its measured effect.
