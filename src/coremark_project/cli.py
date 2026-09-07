"""Command-line interface behind the two public Shell entry points."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .delivery import (
    ContractError,
    ResultMode,
    RunMode,
    Track,
    build_delivery,
    describe_patch_series,
    run_delivery,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coremark")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="create and seal a CoreMark build")
    build.add_argument("--work-root", type=Path)
    build.add_argument("--track", choices=Track, default=Track.K3_DEVELOPMENT)
    build.add_argument(
        "--result-mode", choices=ResultMode, default=ResultMode.BEST_ACHIEVABLE
    )
    build.add_argument("--compiler", type=Path)
    build.add_argument("--compiler-artifact", type=Path)
    build.add_argument("--packages-index", type=Path)
    build.add_argument("--print-patch-series", action="store_true")

    run = commands.add_parser("run", help="run and seal official CoreMark samples")
    run.add_argument("--work-root", type=Path)
    run.add_argument("--evidence-root", type=Path)
    run.add_argument("--out-dir", type=Path)
    run.add_argument("--track", choices=Track, default=Track.K3_DEVELOPMENT)
    run.add_argument(
        "--result-mode", choices=ResultMode, default=ResultMode.BEST_ACHIEVABLE
    )
    modes = run.add_mutually_exclusive_group()
    modes.add_argument("--quick", dest="run_mode", action="store_const", const=RunMode.QUICK)
    modes.add_argument("--formal", dest="run_mode", action="store_const", const=RunMode.FORMAL)
    run.set_defaults(run_mode=RunMode.QUICK)
    run.add_argument("--cpu-set")
    run.add_argument("--runtime-profile-digest")
    return parser


def _environment_path(explicit: Path | None, name: str) -> Path | None:
    if explicit is not None:
        return explicit
    value = os.environ.get(name)
    return Path(value) if value else None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            if args.print_patch_series:
                print(describe_patch_series())
                return 0
            output = build_delivery(
                work_root=_environment_path(args.work_root, "COREMARK_WORK_ROOT"),
                track=Track(args.track),
                result_mode=ResultMode(args.result_mode),
                compiler=_environment_path(args.compiler, "COREMARK_CC"),
                compiler_artifact=_environment_path(
                    args.compiler_artifact, "K3_LLVM_DEB"
                ),
                packages_index=_environment_path(args.packages_index, "K3_LLVM_PACKAGES"),
            )
        else:
            output = run_delivery(
                work_root=_environment_path(args.work_root, "COREMARK_WORK_ROOT"),
                evidence_root=_environment_path(
                    args.evidence_root, "COREMARK_EVIDENCE_ROOT"
                ),
                out_dir=_environment_path(args.out_dir, "COREMARK_OUTDIR"),
                track=Track(args.track),
                result_mode=ResultMode(args.result_mode),
                run_mode=RunMode(args.run_mode),
                cpu_set=args.cpu_set or os.environ.get("COREMARK_CPUSET", "0"),
                runtime_profile_digest=args.runtime_profile_digest
                or os.environ.get("COREMARK_RUNTIME_PROFILE_DIGEST"),
            )
    except ContractError as error:
        print(f"coremark: {error}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
