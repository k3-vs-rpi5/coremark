"""Sealed CoreMark build and run workflow."""

from __future__ import annotations

import hashlib
import importlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from statistics import fmean


class ContractError(RuntimeError):
    """A public-delivery invariant failed closed."""


class Track(StrEnum):
    RPI_NATIVE = "rpi-native"
    K3_COMPATIBLE = "k3-compatible"
    K3_DEVELOPMENT = "k3-development"


class ResultMode(StrEnum):
    DEFAULT_PARITY = "default-parity"
    BEST_ACHIEVABLE = "best-achievable"


class RunMode(StrEnum):
    QUICK = "quick"
    FORMAL = "formal"


SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ENTRYPOINT = PROJECT_ROOT / "scripts/build.sh"
RUN_ENTRYPOINT = PROJECT_ROOT / "scripts/run.sh"
SOURCE_URL = "https://github.com/eembc/coremark.git"
SOURCE_COMMIT = "b56889a7bd9d5624fbeff2a73ba69878e6a9c146"
SOURCE_SHA256 = {
    "core_list_join.c": "ca00e4e010ece47d7f040cb92aa50a95345a00d3171b59d088f6b243be06ce7b",
    "core_main.c": "17884c93c5b94378eb0ff02b4df3725756cf2addb9b8cbcaa6200a4649ff5ca7",
    "core_matrix.c": "ecdff717b5a5c4907d221a606760e25499899cbf617582c05d40db71c91351e4",
    "core_state.c": "f4b84bb0a3452c45a4daa664ab502bfdccbd31cb57d93e9ac490c60937717a4e",
    "core_util.c": "a3fbfcb9bb943b638624b8ece01c5836dd56a96d7bcde2697b248d077447327f",
    "coremark.h": "29f7eb0f0bdf6002f6c7dccfa4f8f9f32c0b8f6709f6538c2b73221938a9c8f1",
}
RUNTIME_POLICY = {
    Track.RPI_NATIVE: {"frequency_mhz": 2400, "tolerance_mhz": 20, "governor": "performance"},
    Track.K3_COMPATIBLE: {"frequency_mhz": 2000, "tolerance_mhz": 20, "governor": "userspace"},
    Track.K3_DEVELOPMENT: {"frequency_mhz": 2000, "tolerance_mhz": 20, "governor": "userspace"},
}


def _require_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise ContractError(f"{name} is required")
    if not value.is_absolute() or value == Path("/"):
        raise ContractError(f"{name} must be an absolute non-root path")
    return value


def _validate_track_architecture(track: Track) -> None:
    from .manifests import expected_runtime_architecture

    expected = expected_runtime_architecture(str(track))
    actual = platform.machine()
    if actual != expected:
        raise ContractError(
            f"{track} requires host architecture {expected}, found {actual}"
        )


def _validate_runtime_policy(track: Track, cpu_set: str) -> None:
    state, frequencies, _ = _platform_state(cpu_set)
    policy = RUNTIME_POLICY[track]
    expected_frequency = int(policy["frequency_mhz"])
    tolerance = int(policy["tolerance_mhz"])
    for cpu in _cpu_ids(cpu_set):
        name = f"cpu{cpu}"
        value = frequencies.get(name)
        if value is None or abs(round(value / 1000) - expected_frequency) > tolerance:
            raise ContractError(f"CPU frequency is not fixed at {expected_frequency} MHz")
        governor = _single_match(
            rf"^{name}_governor=(.+)$",
            state,
            f"{name} governor",
        )
        if governor != policy["governor"]:
            raise ContractError(f"CPU governor is not {policy['governor']}")


@dataclass(frozen=True)
class RunRequest:
    work_root: Path
    evidence_root: Path
    out_dir: Path
    track: Track
    result_mode: ResultMode
    run_mode: RunMode
    cpu_set: str
    runtime_profile_digest: str


@dataclass(frozen=True)
class OfficialResult:
    duration_seconds: float
    iterations_per_second: float
    average_frequency_mhz: dict[str, float] | None = None
    average_temperature_celsius: dict[str, float] | None = None


def prepare_run_request(
    *,
    work_root: Path,
    evidence_root: Path,
    out_dir: Path,
    track: Track,
    result_mode: ResultMode,
    run_mode: RunMode,
    cpu_set: str,
    runtime_profile_digest: str,
) -> RunRequest:
    _validate_track_architecture(track)
    work_root = _require_path(work_root, "COREMARK_WORK_ROOT")
    evidence_root = _require_path(evidence_root, "COREMARK_EVIDENCE_ROOT")
    out_dir = _require_path(out_dir, "COREMARK_OUTDIR")
    if evidence_root.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise ContractError("COREMARK_EVIDENCE_ROOT must be outside the project repository")
    try:
        out_dir.resolve().relative_to(evidence_root.resolve())
    except ValueError as error:
        raise ContractError(f"COREMARK_OUTDIR must be below {evidence_root}") from error
    if out_dir.resolve() == evidence_root.resolve() or out_dir.name in {"", ".", ".."}:
        raise ContractError("COREMARK_OUTDIR must name a new run directory")
    if re.fullmatch(r"[0-9]+(?:[-,][0-9]+)*", cpu_set) is None:
        raise ContractError("COREMARK_CPUSET must be a taskset CPU list")
    if SHA256_RE.fullmatch(runtime_profile_digest) is None:
        raise ContractError("COREMARK_RUNTIME_PROFILE_DIGEST must be a lowercase SHA256")
    from .manifests import expected_runtime_profile_digest

    expected_digest = expected_runtime_profile_digest(str(track))
    if runtime_profile_digest != expected_digest:
        raise ContractError(
            f"runtime profile digest does not match environments.lock.yaml for {track}"
        )
    _validate_runtime_policy(track, cpu_set)
    return RunRequest(
        work_root=work_root,
        evidence_root=evidence_root,
        out_dir=out_dir,
        track=track,
        result_mode=result_mode,
        run_mode=run_mode,
        cpu_set=cpu_set,
        runtime_profile_digest=runtime_profile_digest,
    )


_EXPECTED_CRC = {
    "performance": ("0xe9f5", "0xe714", "0x1fd7", "0x8e3a"),
    "validation": ("0x18f2", "0xe3c1", "0x0747", "0x8d84"),
}


def _single_match(pattern: str, output: str, label: str) -> str:
    matches = re.findall(pattern, output, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ContractError(f"official CoreMark {label} is missing or duplicated")
    return matches[0]


def parse_official_output(mode: str, output: str) -> OfficialResult:
    if mode not in _EXPECTED_CRC:
        raise ContractError(f"unknown CoreMark mode: {mode}")
    duration = float(
        _single_match(r"^Total time \(secs\):\s*([0-9.]+)\s*$", output, "duration")
    )
    if duration < 10:
        raise ContractError("official CoreMark duration is below 10 seconds")
    score = float(
        _single_match(r"^Iterations/Sec\s*:\s*([0-9.]+)\s*$", output, "score")
    )
    expected = _EXPECTED_CRC[mode]
    patterns = (
        r"^seedcrc\s*:\s*(0x[0-9a-fA-F]{4})\s*$",
        r"^\[0\]crclist\s*:\s*(0x[0-9a-fA-F]{4})\s*$",
        r"^\[0\]crcmatrix\s*:\s*(0x[0-9a-fA-F]{4})\s*$",
        r"^\[0\]crcstate\s*:\s*(0x[0-9a-fA-F]{4})\s*$",
    )
    actual = tuple(_single_match(pattern, output, "CRC").lower() for pattern in patterns)
    if actual != expected:
        raise ContractError(f"official CoreMark {mode} CRC mismatch")
    _single_match(r"^\[0\]crcfinal\s*:\s*(0x[0-9a-fA-F]{4})\s*$", output, "final CRC")
    if output.count("Correct operation validated.") != 1:
        raise ContractError("official CoreMark success marker is missing or duplicated")
    return OfficialResult(duration, score)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seal_checksums(root: Path) -> Path:
    checksum_path = root / "SHA256SUMS"
    entries = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path == checksum_path:
            continue
        relative = path.relative_to(root)
        if path.is_symlink() or ".." in relative.parts:
            raise ContractError(f"unsafe evidence path: {relative}")
        entries.append(f"{_sha256(path)}  {relative.as_posix()}\n")
    checksum_path.write_text("".join(entries), encoding="utf-8")
    return checksum_path


def verify_checksum_closure(root: Path, checksum_path: Path) -> None:
    if checksum_path != root / "SHA256SUMS" or not checksum_path.is_file():
        raise ContractError("checksum closure path is invalid")
    declared: set[Path] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ContractError("checksum closure contains a malformed entry")
        relative = Path(match.group(2))
        if relative.is_absolute() or ".." in relative.parts or relative in declared:
            raise ContractError(f"checksum closure contains an unsafe path: {relative}")
        path = root / relative
        if not path.is_file() or path.is_symlink() or _sha256(path) != match.group(1):
            raise ContractError(f"checksum mismatch: {relative}")
        declared.add(relative)
    actual = {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if declared != actual:
        raise ContractError("checksum closure does not cover every evidence file")


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _clean_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONSAFEPATH"] = "1"
    if extra:
        environment.update(extra)
    return environment


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    log: Path | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment or _clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise ContractError(f"cannot execute command: {command[0]}: {error}") from error
    if log is not None:
        log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise ContractError(f"command failed ({completed.returncode}): {command[0]}{suffix}")
    return completed.stdout


def _python_yaml_identity() -> dict:
    try:
        yaml_module = importlib.import_module("yaml")
    except ModuleNotFoundError:
        _run_command(["sudo", "apt-get", "update"])
        _run_command(["sudo", "apt-get", "install", "-y", "python3-yaml"])
        yaml_module = importlib.import_module("yaml")
    status = _run_command(
        ["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", "python3-yaml"]
    ).strip()
    fields = status.split("|", 1)
    if len(fields) != 2 or fields[0].strip() != "ii":
        raise ContractError("PyYAML must be installed through APT package python3-yaml")
    module_path = Path(yaml_module.__file__).resolve(strict=True)
    owned_paths = set(
        _run_command(["dpkg-query", "-L", "python3-yaml"]).splitlines()
    )
    if str(module_path) not in owned_paths:
        raise ContractError("loaded PyYAML module is not owned by APT package python3-yaml")
    return {
        "package": "python3-yaml",
        "package_version": fields[1],
        "module_version": str(yaml_module.__version__),
        "module_path": str(module_path),
        "module_sha256": _sha256(module_path),
    }


def _yaml_module():
    return importlib.import_module("yaml")


def _new_directory(path: Path, label: str) -> Path:
    path = _require_path(path, label)
    if path.exists() or path.is_symlink():
        raise ContractError(f"{label} must name a new path: {path}")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        canonical_parent = parent.resolve(strict=True)
    except OSError as error:
        raise ContractError(f"{label} parent cannot be resolved: {parent}") from error
    if canonical_parent != parent:
        raise ContractError(f"{label} parent must not traverse a symlink: {parent}")
    path.mkdir()
    return path


def _resolve_compiler(value: Path | None) -> Path:
    command = str(value) if value else "cc"
    resolved = shutil.which(command)
    if resolved is None:
        raise ContractError(f"compiler is missing; install it through APT: {command}")
    return Path(resolved).resolve(strict=True)


def _verify_source(source_root: Path, evidence: Path) -> None:
    head = _run_command(["git", "-C", str(source_root), "rev-parse", "HEAD"]).strip()
    if head != SOURCE_COMMIT:
        raise ContractError(f"official CoreMark source commit mismatch: {head}")
    status = _run_command(
        ["git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=all"]
    )
    if status:
        raise ContractError("official CoreMark checkout is not clean")
    for relative, expected in SOURCE_SHA256.items():
        path = source_root / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ContractError(f"checksum-controlled CoreMark source mismatch: {relative}")
    _run_command(["make", "-C", str(source_root), "check"], log=evidence)


def _write_yaml(path: Path, document: dict) -> None:
    path.write_text(
        _yaml_module().safe_dump(document, sort_keys=False), encoding="utf-8"
    )


def _toolchain_identity(compiler: Path) -> dict:
    version = _run_command([str(compiler), "--version"]).strip()
    target = _run_command([str(compiler), "-dumpmachine"]).strip()
    return {
        "compiler_path": str(compiler),
        "compiler_sha256": _sha256(compiler),
        "compiler_version": version,
        "compiler_target": target,
    }


def _ensure_x100_toolchain(
    compiler: Path | None,
    artifact: Path | None,
    packages_index: Path | None,
    work_root: Path,
    evidence: Path,
) -> Path:
    from .manifests import load_toolchain_lock

    lock = load_toolchain_lock()
    compiler_path = compiler or lock.compiler_path
    if compiler_path != lock.compiler_path:
        raise ContractError(f"best-achievable compiler must be {lock.compiler_path}")
    if platform.machine() != lock.architecture:
        raise ContractError(f"locked X100 compiler requires {lock.architecture}")
    if artifact is None or not artifact.is_file():
        raise ContractError("K3_LLVM_DEB must name the downloaded locked compiler package")
    if _sha256(artifact) != lock.package_sha256:
        raise ContractError("locked compiler package SHA256 mismatch")
    package_fields = {
        field: _run_command(["dpkg-deb", "-f", str(artifact), field]).strip()
        for field in ("Package", "Version", "Architecture")
    }
    if package_fields != {
        "Package": lock.package_name,
        "Version": lock.package_version,
        "Architecture": lock.architecture,
    }:
        raise ContractError("locked compiler package metadata mismatch")

    apt_root = work_root / "apt/llvm-a0df86d"
    apt_root.mkdir(parents=True)
    local_artifact = apt_root / artifact.name
    shutil.copy2(artifact, local_artifact)
    local_packages = apt_root / "Packages"
    if packages_index is not None:
        if not packages_index.is_file() or _sha256(packages_index) != lock.packages_index_sha256:
            raise ContractError("APT Packages index SHA256 mismatch")
        shutil.copy2(packages_index, local_packages)
    else:
        output = _run_command(["dpkg-scanpackages", ".", "/dev/null"], cwd=apt_root)
        local_packages.write_text(output, encoding="utf-8")
        if _sha256(local_packages) != lock.packages_index_sha256:
            raise ContractError(
                "generated APT Packages index does not match the lock; provide K3_LLVM_PACKAGES"
            )

    installed = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", lock.package_name],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    installed_fields = installed.split("|", 1)
    installed_exact = (
        len(installed_fields) == 2
        and installed_fields[0].strip() == "ii"
        and installed_fields[1] == lock.package_version
    )
    if not installed_exact:
        source = apt_root / "k3-coremark.list"
        sourceparts = apt_root / "sourceparts"
        sourceparts.mkdir()
        source.write_text(f"deb [trusted=yes] file:{apt_root} ./\n", encoding="utf-8")
        apt_options = [
            "sudo",
            "apt-get",
            "-o",
            f"Dir::Etc::sourcelist={source}",
            "-o",
            f"Dir::Etc::sourceparts={sourceparts}",
        ]
        _run_command([*apt_options, "update"], log=evidence / "apt-update.log")
        _run_command(
            [*apt_options, "install", "-y", f"{lock.package_name}={lock.package_version}"],
            log=evidence / "apt-install.log",
        )
    installed = _run_command(
        ["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", lock.package_name]
    ).strip()
    installed_fields = installed.split("|", 1)
    if not (
        len(installed_fields) == 2
        and installed_fields[0].strip() == "ii"
        and installed_fields[1] == lock.package_version
    ):
        raise ContractError("locked compiler APT package is not installed at the exact version")
    if not compiler_path.is_file() or not os.access(compiler_path, os.X_OK):
        raise ContractError(f"locked compiler executable is missing: {compiler_path}")
    if _sha256(compiler_path) != lock.compiler_sha256:
        raise ContractError("locked compiler executable SHA256 mismatch")
    if _run_command([str(compiler_path), "-dumpmachine"]).strip() != "riscv64-unknown-linux-gnu":
        raise ContractError("locked compiler target mismatch")
    version = _run_command([str(compiler_path), "--version"])
    if "clang version 23.0.0git" not in version:
        raise ContractError("locked compiler version output mismatch")
    verification = {
        "status": "passed",
        "package": lock.package_name,
        "version": lock.package_version,
        "architecture": lock.architecture,
        "package_sha256": lock.package_sha256,
        "packages_index_sha256": lock.packages_index_sha256,
        "compiler_sha256": lock.compiler_sha256,
        "llvm_commit": lock.llvm_commit,
    }
    _write_yaml(evidence / "toolchain-verification.yaml", verification)
    return compiler_path


def _compile_mode(
    source_root: Path,
    output: Path,
    compiler: Path,
    port_dir: str,
    result_mode: ResultMode,
    mode: str,
    evidence: Path,
    port_flags: str | None = None,
) -> None:
    macro = "-DPERFORMANCE_RUN=1" if mode == "performance" else "-DVALIDATION_RUN=1"
    optimization = "-O3" if result_mode is ResultMode.BEST_ACHIEVABLE else "-O2"
    flags = f"{optimization} {macro}"
    (evidence / f"{mode}-flags.txt").write_text(flags + "\n", encoding="utf-8")
    _run_command(
        ["make", "-C", str(source_root), "clean"],
        log=evidence / f"{mode}-clean.log",
    )
    command = [
        "make",
        "-C",
        str(source_root),
        f"PORT_DIR={port_dir}",
        f"CC={compiler}",
        f"XCFLAGS={flags}",
    ]
    if port_flags:
        command.append(f"PORT_CFLAGS={port_flags}")
    command.append("compile")
    _run_command(command, log=evidence / f"{mode}-build.log")
    binary = source_root / "coremark.exe"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ContractError(f"CoreMark {mode} build did not produce an executable")
    shutil.copy2(binary, output)


def _compatible_compiler(work_root: Path, source_root: Path, evidence: Path) -> Path:
    rootfs_text = os.environ.get("COREMARK_ROOTFS")
    if not rootfs_text:
        raise ContractError("k3-compatible requires COREMARK_ROOTFS")
    rootfs = Path(rootfs_text)
    if not rootfs.is_absolute() or rootfs.resolve(strict=True) != rootfs:
        raise ContractError("COREMARK_ROOTFS must be an absolute canonical directory")
    compiler = rootfs / "usr/bin/gcc"
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ContractError("locked rootfs GCC is missing; install it through rootfs APT")
    wrapper = work_root / "bin/rootfs-compiler"
    wrapper.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"exec bwrap --die-with-parent --ro-bind '{rootfs}' / --dev /dev --proc /proc "
        f"--tmpfs /tmp --bind '{source_root}' /tmp/coremark-source "
        "--chdir /tmp/coremark-source --setenv PATH "
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin /usr/bin/gcc \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    identity = {
        "compiler_path_in_rootfs": "/usr/bin/gcc",
        "compiler_sha256": _sha256(compiler),
        "compiler_version": _run_command(
            [
                "bwrap",
                "--ro-bind",
                str(rootfs),
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "/usr/bin/gcc",
                "--version",
            ]
        ).strip(),
        "rootfs": str(rootfs),
    }
    _write_yaml(evidence / "compatible-toolchain.yaml", identity)
    return wrapper


def describe_patch_series() -> str:
    _python_yaml_identity()
    from .manifests import public_patch_series

    series = public_patch_series()
    lines = [
        f"series_id={series.series_id}",
        f"source_commit={series.source_commit}",
        f"series_sha256={series.series_sha256}",
    ]
    lines.extend(
        f"patch_{index}={record.path}|{record.sha256}"
        for index, record in enumerate(series.patches, start=1)
    )
    return "\n".join(lines)


def build_delivery(
    *,
    work_root: Path | None,
    compiler_kind: str = "default",
    track: Track,
    result_mode: ResultMode,
    compiler: Path | None,
    compiler_artifact: Path | None,
    packages_index: Path | None,
) -> Path:
    from .manifests import (
        apply_patch_series,
        load_patch_series,
        reverse_patch_series,
    )

    if compiler_kind not in {"default", "clang23-pgo"}:
        raise ContractError(f"unknown compiler kind: {compiler_kind}")
    if compiler_kind == "clang23-pgo" and not (
        track is Track.K3_DEVELOPMENT and result_mode is ResultMode.BEST_ACHIEVABLE
    ):
        raise ContractError(
            "the clang23-pgo lane is limited to k3-development best-achievable"
        )
    if compiler_kind == "clang23-pgo":
        # The locked lane is a cross build: the clang host package is x86_64 and
        # the target is riscv64 with the SpacemiT sysroot, so the native
        # host/target architecture equality gate does not apply.
        if platform.machine() != "x86_64":
            raise ContractError("the clang23-pgo lane requires an x86_64 host")
    else:
        _validate_track_architecture(track)
    if work_root is None:
        # No work root was named, so the temporary directory this creates IS the
        # work root. It must not be pushed through _new_directory, which requires
        # a path that does not exist yet - that check made the default form of
        # `scripts/build.sh` fail with "must name a new path" for the directory
        # it had just created a line earlier.
        work_root = Path(tempfile.mkdtemp(prefix="coremark-build-"))
    else:
        work_root = _new_directory(work_root, "COREMARK_WORK_ROOT")
    evidence = work_root / "evidence"
    binaries = work_root / "bin"
    source_root = work_root / "source"
    evidence.mkdir()
    binaries.mkdir()
    patch_series = None
    patch_applied = False
    lane_port_flags: str | None = None

    try:
        parser_identity = _python_yaml_identity()
        _write_yaml(evidence / "manifest-parser.yaml", parser_identity)
        _run_command(
            ["git", "clone", SOURCE_URL, str(source_root)],
            log=evidence / "source-clone.log",
        )
        _run_command(
            ["git", "-C", str(source_root), "checkout", "--detach", SOURCE_COMMIT],
            log=evidence / "source-checkout.log",
        )
        _verify_source(source_root, evidence / "source-check-before-patch.log")

        if (
            result_mode is ResultMode.BEST_ACHIEVABLE
            and track is Track.K3_DEVELOPMENT
        ):
            if compiler_kind == "clang23-pgo":
                from .clang_pgo import locked_port_flags, prepare_compiler

                compiler_path = prepare_compiler(work_root, evidence)
                lane_port_flags = locked_port_flags()
            else:
                compiler_path = _ensure_x100_toolchain(
                    compiler,
                    compiler_artifact,
                    packages_index,
                    work_root,
                    evidence,
                )
            patch_series = load_patch_series()
            apply_patch_series(source_root, patch_series)
            patch_applied = True
            _run_command(
                ["make", "-C", str(source_root), "check"],
                log=evidence / "source-check-after-patch.log",
            )
            port_dir = "linux-spacemit-x100"
        elif track is Track.K3_COMPATIBLE:
            compiler_path = _compatible_compiler(work_root, source_root, evidence)
            port_dir = "linux"
        else:
            compiler_path = _resolve_compiler(compiler)
            port_dir = "linux"

        identity = _toolchain_identity(compiler_path)
        _write_yaml(evidence / "toolchain-identity.yaml", identity)
        for mode in ("performance", "validation"):
            _compile_mode(
                source_root,
                binaries / f"coremark-{mode}.exe",
                compiler_path,
                port_dir,
                result_mode,
                mode,
                evidence,
                lane_port_flags,
            )

        _run_command(
            ["make", "-C", str(source_root), "clean"],
            log=evidence / "source-final-clean.log",
        )
        if patch_series is not None:
            reverse_patch_series(source_root, patch_series)
            patch_applied = False
        _verify_source(source_root, evidence / "source-check-after-reverse.log")
        build_manifest = {
            "schema_version": 1,
            "status": "completed",
            "track": str(track),
            "result_mode": str(result_mode),
            "compiler_kind": compiler_kind,
            "source": {
                "url": SOURCE_URL,
                "commit": SOURCE_COMMIT,
                "integrity_check": "make check",
                "checksum_controlled_sha256": SOURCE_SHA256,
            },
            "port_dir": port_dir,
            "compiler": identity,
            "manifest_parser": parser_identity,
            "patch_series": (
                {
                    "id": patch_series.series_id,
                    "sha256": patch_series.series_sha256,
                    "application": "zero-fuzz-forward-and-reverse",
                }
                if patch_series
                else None
            ),
            "binaries": {
                mode: {
                    "path": f"bin/coremark-{mode}.exe",
                    "sha256": _sha256(binaries / f"coremark-{mode}.exe"),
                }
                for mode in ("performance", "validation")
            },
            "implementation_sha256": _sha256(Path(__file__)),
            "public_entrypoints": {
                "build_sha256": _sha256(BUILD_ENTRYPOINT),
                "run_sha256": _sha256(RUN_ENTRYPOINT),
            },
            "source_clean_after_build": True,
        }
        _write_yaml(work_root / "build-manifest.yaml", build_manifest)
        seal_checksums(work_root)
        verify_checksum_closure(work_root, work_root / "SHA256SUMS")
        return work_root
    except BaseException:
        if patch_applied and patch_series is not None and source_root.is_dir():
            try:
                _run_command(["make", "-C", str(source_root), "clean"])
                reverse_patch_series(source_root, patch_series)
            except ContractError as cleanup_error:
                (evidence / "cleanup-error.txt").write_text(
                    str(cleanup_error) + "\n", encoding="utf-8"
                )
        raise


def _read_text(path: Path, missing: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return f"not-recorded:{missing}"


def _cpu_ids(cpu_set: str) -> list[int]:
    values: set[int] = set()
    for component in cpu_set.split(","):
        if "-" in component:
            start, end = (int(value) for value in component.split("-", 1))
            if end < start:
                raise ContractError("COREMARK_CPUSET range is reversed")
            values.update(range(start, end + 1))
        else:
            values.add(int(component))
    return sorted(values)


def _platform_state(cpu_set: str) -> tuple[str, dict[str, int], dict[str, int]]:
    lines = [
        f"captured_at_utc={datetime.now(UTC).isoformat()}",
        f"boot_id={_read_text(Path('/proc/sys/kernel/random/boot_id'), 'unavailable')}",
        f"cpuset={cpu_set}",
        f"kernel={platform.release()}",
        f"machine={platform.machine()}",
    ]
    frequencies: dict[str, int] = {}
    for cpu in _cpu_ids(cpu_set):
        base = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
        value = _read_text(base / "scaling_cur_freq", "current-frequency-unavailable")
        lines.append(f"cpu{cpu}_cur_freq_khz={value}")
        if value.isdigit():
            frequencies[f"cpu{cpu}"] = int(value)
        lines.append(
            f"cpu{cpu}_governor="
            f"{_read_text(base / 'scaling_governor', 'governor-unavailable')}"
        )
    temperatures: dict[str, int] = {}
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        value = _read_text(path, "temperature-unavailable")
        zone = path.parent.name
        lines.append(f"{zone}_temperature_millicelsius={value}")
        if value.lstrip("-").isdigit():
            temperatures[zone] = int(value)
    lines.extend(
        [
            f"cpu_online={_read_text(Path('/sys/devices/system/cpu/online'), 'unavailable')}",
            f"loadavg={_read_text(Path('/proc/loadavg'), 'unavailable')}",
            f"swap={_read_text(Path('/proc/swaps'), 'unavailable')}",
        ]
    )
    return "\n".join(lines) + "\n", frequencies, temperatures


def _capture_run_context(out_root: Path, cpu_set: str) -> None:
    diagnostics = out_root / "diagnostics"
    state, _, _ = _platform_state(cpu_set)
    (diagnostics / "platform-initial.txt").write_text(state, encoding="utf-8")
    for source, name in (
        (Path("/etc/os-release"), "os-release.txt"),
        (Path("/proc/cpuinfo"), "cpuinfo.txt"),
        (Path("/proc/meminfo"), "meminfo.txt"),
        (Path("/proc/mounts"), "mounts.txt"),
        (Path("/proc/cmdline"), "kernel-command-line.txt"),
    ):
        (diagnostics / name).write_text(
            _read_text(source, source.as_posix()) + "\n", encoding="utf-8"
        )
    network_lines: list[str] = []
    for interface in sorted(Path("/sys/class/net").glob("*")):
        network_lines.extend(
            [
                f"{interface.name}.operstate={_read_text(interface / 'operstate', 'unavailable')}",
                f"{interface.name}.speed_mbps={_read_text(interface / 'speed', 'unavailable')}",
            ]
        )
    (diagnostics / "network.txt").write_text(
        "\n".join(network_lines) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend"],
        text=True,
        capture_output=True,
        check=False,
    )
    (diagnostics / "active-services.txt").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    throttle_command = shutil.which("vcgencmd")
    throttle_text = "not-applicable-or-unavailable\n"
    if throttle_command:
        throttle = subprocess.run(
            [throttle_command, "get_throttled"],
            text=True,
            capture_output=True,
            check=False,
        )
        throttle_text = throttle.stdout + throttle.stderr
    (diagnostics / "throttling.txt").write_text(throttle_text, encoding="utf-8")


def _sample_command(request: RunRequest, binary: Path, mode: str) -> list[str]:
    arguments = ["0", "0", "0x66", "0"]
    if mode == "validation":
        arguments[:2] = ["0x3415", "0x3415"]
    if request.track is Track.K3_COMPATIBLE:
        rootfs_text = os.environ.get("COREMARK_ROOTFS")
        if not rootfs_text:
            raise ContractError("k3-compatible requires COREMARK_ROOTFS")
        rootfs = Path(rootfs_text)
        if not rootfs.is_absolute() or rootfs.resolve(strict=True) != rootfs:
            raise ContractError("COREMARK_ROOTFS must be an absolute canonical directory")
        return [
            "taskset",
            "-c",
            request.cpu_set,
            "bwrap",
            "--ro-bind",
            str(rootfs),
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            str(binary.parent),
            "/tmp/coremark-bin",
            "--chdir",
            "/tmp/coremark-bin",
            f"/tmp/coremark-bin/{binary.name}",
            *arguments,
        ]
    return ["taskset", "-c", request.cpu_set, str(binary), *arguments]


def _run_sample(
    request: RunRequest,
    binary: Path,
    mode: str,
    log: Path,
    telemetry: Path,
) -> OfficialResult:
    command = _sample_command(request, binary, mode)
    samples: list[str] = []
    frequencies: dict[str, list[int]] = {}
    temperatures: dict[str, list[int]] = {}
    try:
        process = subprocess.Popen(
            command,
            env=_clean_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        raise ContractError(f"cannot execute CoreMark: {error}") from error
    try:
        while process.poll() is None:
            state, current_frequencies, current_temperatures = _platform_state(
                request.cpu_set
            )
            samples.append(state)
            for name, value in current_frequencies.items():
                frequencies.setdefault(name, []).append(value)
            for name, value in current_temperatures.items():
                temperatures.setdefault(name, []).append(value)
            time.sleep(1)
        output, _ = process.communicate()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    log.write_text(output, encoding="utf-8")
    telemetry.write_text("\n".join(samples), encoding="utf-8")
    if process.returncode != 0:
        raise ContractError(f"CoreMark {mode} execution failed with status {process.returncode}")
    if not frequencies or not temperatures:
        raise ContractError("frequency or temperature telemetry is missing")
    parsed = parse_official_output(mode, output)
    return OfficialResult(
        duration_seconds=parsed.duration_seconds,
        iterations_per_second=parsed.iterations_per_second,
        average_frequency_mhz={
            name: round(fmean(values) / 1000, 6) for name, values in frequencies.items()
        },
        average_temperature_celsius={
            name: round(fmean(values) / 1000, 6) for name, values in temperatures.items()
        },
    )


def _execution_plan(run_mode: RunMode) -> list[tuple[str, int, int, bool]]:
    """Return mode, sessions, samples, and whether samples enter the result."""
    sessions, samples = (3, 30) if run_mode is RunMode.FORMAL else (1, 1)
    return [
        ("validation", sessions, samples, True),
        ("performance", 1, 3, False),
        ("performance", sessions, samples, True),
    ]


def _seal_failed_run(out_root: Path, error: BaseException) -> None:
    """Retain a failed run without allowing it to become publishable evidence."""
    _write_yaml(
        out_root / "manifest.yaml",
        {
            "schema_version": 1,
            "status": "invalid",
            "public_claim": False,
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "error_type": type(error).__name__,
            "error": str(error),
        },
    )
    checksum_path = seal_checksums(out_root)
    verify_checksum_closure(out_root, checksum_path)


def run_delivery(
    *,
    work_root: Path | None,
    evidence_root: Path | None,
    out_dir: Path | None,
    track: Track,
    result_mode: ResultMode,
    run_mode: RunMode,
    cpu_set: str,
    runtime_profile_digest: str | None,
) -> Path:
    if work_root is None:
        raise ContractError("COREMARK_WORK_ROOT is required; run build.sh first")
    if evidence_root is None:
        raise ContractError("COREMARK_EVIDENCE_ROOT is required")
    if runtime_profile_digest is None:
        raise ContractError("COREMARK_RUNTIME_PROFILE_DIGEST is required")
    _python_yaml_identity()
    if out_dir is None:
        suffix = "formal-3x30" if run_mode is RunMode.FORMAL else "quick-1x1"
        out_dir = evidence_root / "coremark" / (
            f"{_utc_stamp()}-{track}-{result_mode}-{suffix}"
        )
    request = prepare_run_request(
        work_root=work_root,
        evidence_root=evidence_root,
        out_dir=out_dir,
        track=track,
        result_mode=result_mode,
        run_mode=run_mode,
        cpu_set=cpu_set,
        runtime_profile_digest=runtime_profile_digest,
    )
    if not request.work_root.is_dir():
        raise ContractError(f"build workspace is missing: {request.work_root}")
    verify_checksum_closure(request.work_root, request.work_root / "SHA256SUMS")
    manifest_path = request.work_root / "build-manifest.yaml"
    yaml_module = _yaml_module()
    try:
        build_manifest = yaml_module.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml_module.YAMLError) as error:
        raise ContractError("build manifest is unreadable") from error
    if (
        not isinstance(build_manifest, dict)
        or build_manifest.get("status") != "completed"
        or build_manifest.get("track") != str(track)
        or build_manifest.get("result_mode") != str(result_mode)
        or build_manifest.get("source", {}).get("commit") != SOURCE_COMMIT
        or build_manifest.get("implementation_sha256") != _sha256(Path(__file__))
        or build_manifest.get("public_entrypoints")
        != {
            "build_sha256": _sha256(BUILD_ENTRYPOINT),
            "run_sha256": _sha256(RUN_ENTRYPOINT),
        }
    ):
        raise ContractError("build manifest identity does not match the requested run")

    request.out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_root = _new_directory(request.out_dir, "COREMARK_OUTDIR")
    for directory in (
        "diagnostics",
        "diagnostics/warmup",
        "performance",
        "validation",
        "telemetry",
    ):
        (out_root / directory).mkdir()
    _capture_run_context(out_root, request.cpu_set)
    sessions, samples_per_session = (
        (3, 30) if run_mode is RunMode.FORMAL else (1, 1)
    )
    results: list[dict] = []
    verified_binaries: dict[str, Path] = {}
    for mode in ("validation", "performance"):
        binary = request.work_root / f"bin/coremark-{mode}.exe"
        expected_digest = build_manifest.get("binaries", {}).get(mode, {}).get("sha256")
        if not binary.is_file() or _sha256(binary) != expected_digest:
            error = ContractError(f"sealed CoreMark {mode} binary identity mismatch")
            _seal_failed_run(out_root, error)
            raise error
        verified_binaries[mode] = binary
    for mode, phase_sessions, phase_samples, retained in _execution_plan(run_mode):
        binary = verified_binaries[mode]
        for session in range(1, phase_sessions + 1):
            for sample in range(1, phase_samples + 1):
                stem = f"session-{session}-sample-{sample}"
                if retained:
                    log = out_root / mode / f"{stem}.log"
                    telemetry = out_root / "telemetry" / f"{mode}-{stem}.txt"
                else:
                    log = out_root / "diagnostics/warmup" / f"{stem}.log"
                    telemetry = (
                        out_root / "diagnostics/warmup" / f"{stem}-telemetry.txt"
                    )
                try:
                    result = _run_sample(
                        request,
                        binary,
                        mode,
                        log,
                        telemetry,
                    )
                except BaseException as error:
                    _seal_failed_run(out_root, error)
                    raise
                if not retained:
                    continue
                results.append(
                    {
                        "mode": mode,
                        "session": session,
                        "sample": sample,
                        "duration_seconds": result.duration_seconds,
                        "iterations_per_second": result.iterations_per_second,
                        "average_frequency_mhz": result.average_frequency_mhz,
                        "average_temperature_celsius": (
                            result.average_temperature_celsius
                        ),
                    }
                )
    performance_results = [item for item in results if item["mode"] == "performance"]
    frequency_values = [
        value
        for item in performance_results
        for value in item["average_frequency_mhz"].values()
    ]
    temperature_by_zone: dict[str, list[float]] = {}
    for item in performance_results:
        for zone, value in item["average_temperature_celsius"].items():
            temperature_by_zone.setdefault(zone, []).append(value)
    mean_score = fmean(item["iterations_per_second"] for item in performance_results)
    mean_frequency = fmean(frequency_values)
    final_state, _, _ = _platform_state(request.cpu_set)
    (out_root / "diagnostics/platform-final.txt").write_text(
        final_state, encoding="utf-8"
    )
    run_manifest = {
        "schema_version": 1,
        "cycle": "coremark-three-track",
        "run_id": out_root.name,
        "status": "completed",
        "public_claim": False,
        "result_class": (
            "formal-reportable-after-independent-review"
            if run_mode is RunMode.FORMAL
            else "quick-functional-only-not-reportable"
        ),
        "track": str(track),
        "result_mode": str(result_mode),
        "run_mode": str(run_mode),
        "cpu_set": request.cpu_set,
        "runtime_profile_digest": request.runtime_profile_digest,
        "boot_id": _read_text(Path("/proc/sys/kernel/random/boot_id"), "unavailable"),
        "source_commit": SOURCE_COMMIT,
        "build_manifest_sha256": _sha256(manifest_path),
        "implementation_sha256": _sha256(Path(__file__)),
        "sessions": sessions,
        "samples_per_session": samples_per_session,
        "warmup_samples": 3,
        "execution_order": ["validation", "performance-warmup", "performance"],
        "official_crc_gate": "passed",
        "minimum_duration_seconds": 10,
        "frequency_and_temperature_telemetry": "captured-per-sample",
        "performance_summary": {
            "mean_iterations_per_second": round(mean_score, 6),
            "measured_average_frequency_mhz": round(mean_frequency, 6),
            "coremark_per_mhz": round(mean_score / mean_frequency, 6),
            "average_temperature_celsius": {
                zone: round(fmean(values), 6)
                for zone, values in sorted(temperature_by_zone.items())
            },
        },
        "samples": results,
    }
    _write_yaml(out_root / "manifest.yaml", run_manifest)
    checksum_path = seal_checksums(out_root)
    verify_checksum_closure(out_root, checksum_path)
    return out_root
