[中文](README.zh-CN.md)

# CoreMark patch policy

This directory contains one accepted public series. Diagnostic and rejected
experiments are not public patch files.

## Accepted series

The sole patch is
[`0001-ports-add-linux-clang-port-for-spacemit-x100.patch`](0001-ports-add-linux-clang-port-for-spacemit-x100.patch).
It adds only `linux-spacemit-x100/core_portme.mak`; checksum-controlled CoreMark
workload files remain unchanged.

The patch targets official source commit
`b56889a7bd9d5624fbeff2a73ba69878e6a9c146`, has SHA256
`1ef3ac808aac18e43c3a8de5b60a9bace8ed1c90e4347f152ffcc2d58e493927`,
and is classified `upstream-ready-not-submitted`.

## Application contract

`manifest.yaml` is authoritative for order and identity. The public build must:

1. pass official `make check` before applying the series;
2. verify the patch digest and apply with `--fuzz=0`;
3. pass official `make check` after application;
4. build and validate with the declared compiler and flags;
5. reverse with `--fuzz=0`, pass `make check`, and leave a clean source tree.

## Rejected work

Earlier workload-source and compiler-workaround diagnostics did not enter the
official-score lane. Their conclusions belong to the CoreMark report in the
separate reports repository; detailed local files remain recoverable from the
pre-migration recovery bundle.
