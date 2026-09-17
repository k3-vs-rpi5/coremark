[中文](AGENTS.zh-CN.md)

# CoreMark project requirements

This project-local contract narrows the workspace contract in the root
`AGENTS.md` and the governance documents; it cannot relax them. It records only
what is specific to CoreMark.

- Cross builds default to the workspace toolchain
  `spacemit-toolchain-linux-glibc-x86_64-v1.2.4/` with its own `sysroot/`, which
  is what the root contract requires. One recorded exception is pending below:
  the sealed `k3_x100_clang_23_pgo` lane was built against the `v1.2.2` sysroot
  and GCC toolchain.
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
- **Pending re-adjudication, needs human approval.** The `k3-compatible` and
  `k3-development` runtime profiles pin a foundation profile digest that predates
  foundation commit `306630b`, which corrected the operating frequency in
  `config/runtime-profiles/k3-compatible-debian13.yaml` and
  `config/runtime-profiles/k3-development-bianbu404.yaml` from `2200 MHz` to
  `2000 MHz`. The lock still records the pre-fix digests
  (`61c40d03e873625d3aa44fc8aa37642f96bbfce9d4334c3d8323cdcfa646f1a4` and
  `62218ec3b29f5a1f33397393826270287d2c5e0fc1b96854f05d8a13d9d32328`), so the run
  gate would accept a digest describing a platform declaration that no longer
  exists. Updating the two pins is an environment-lock change and waits for
  approval; the current digests are
  `484e181fffbfa493dceee66588ef79a05f1cb2bbe95a7452d537bcfca1667214` and
  `36357713156c805b464642b4f07c4dbbcc12bc7298856bf3934d1ee3d9f5b8ec`.
- **Pending re-adjudication, needs human approval.** `environments.lock.yaml`
  records the `k3_x100_clang_23_pgo` target as
  `spacemit-toolchain-linux-glibc-x86_64-v1.2.2`, for both `sysroot` and
  `gcc_toolchain`. No other lane in this project resolves a workspace toolchain
  path, so this is the last `v1.2.2` user left. The sealed best-achievable
  result (8.60 CoreMark/MHz) was produced against that sysroot, so re-pointing
  the lane changes the runtime identity of a recorded result and waits for
  approval and a re-measure; the `v1.2.2` directory has to stay until then.
