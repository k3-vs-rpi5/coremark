[中文](AGENTS.zh-CN.md)

# CoreMark project requirements

This project-local contract narrows the workspace contract in the root
`AGENTS.md` and the governance documents; it cannot relax them. It records only
what is specific to CoreMark.

- Cross builds default to the workspace toolchain
  `spacemit-toolchain-linux-glibc-x86_64-v1.2.2/` with its own `sysroot/`.
- The pinned upstream source is the local checkout `src/coremark` at commit
  `b56889a7bd9d5624fbeff2a73ba69878e6a9c146`, integrity command `make check`,
  with `coremark.md5`-controlled workload files.
- The frozen automation is `src/coremark_project`, reached only through
  `scripts/build.sh` and `scripts/run.sh`.
- Accepted optimizations are frozen into `patches/` as the ordered
  `coremark-k3-x100` series with its `manifest.yaml` entry and bilingual note; a
  compile-parameter optimization with no landing place in `src/coremark` lands
  in `src/coremark_project`.
- Device delivery, execution, and analysis follow the governance workflow
  through the workspace credentials `.ssh-k3` and `.ssh-rpi`, and evidence is
  sealed outside every managed Git repository.
