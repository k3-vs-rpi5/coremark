"""Content-addressed manifest and patch-series boundaries."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import yaml

from .delivery import ContractError

if TYPE_CHECKING:
    from .clang_pgo import ClangPgoLock

LOCKED_SOURCE_COMMIT = "b56889a7bd9d5624fbeff2a73ba69878e6a9c146"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PATCH_MANIFEST = PROJECT_ROOT / "patches/manifest.yaml"
ENVIRONMENT_LOCK = PROJECT_ROOT / "environments.lock.yaml"


@dataclass(frozen=True)
class PatchRecord:
    patch_id: str
    path: Path
    sha256: str

    def absolute_path(self, repository_root: Path) -> Path:
        candidate = repository_root / self.path
        try:
            candidate.resolve(strict=True).relative_to(repository_root.resolve(strict=True))
        except (FileNotFoundError, ValueError) as error:
            raise ContractError(f"patch path escapes or is missing: {self.path}") from error
        return candidate


@dataclass(frozen=True)
class PatchSeries:
    series_id: str
    source_commit: str
    series_sha256: str
    patches: tuple[PatchRecord, ...]


@dataclass(frozen=True)
class ToolchainLock:
    package_name: str
    package_version: str
    architecture: str
    package_sha256: str
    packages_index_sha256: str
    compiler_path: Path
    compiler_sha256: str
    llvm_commit: str


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a mapping")
    return value


def load_patch_series(
    manifest_path: Path = PATCH_MANIFEST,
    repository_root: Path = PROJECT_ROOT,
) -> PatchSeries:
    try:
        document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load patch manifest: {manifest_path}") from error
    document = _mapping(document, "patch manifest")
    if document.get("schema_version") != 1:
        raise ContractError("unsupported patch manifest schema")

    series_data = _mapping(document.get("public_delivery_series"), "public patch series")
    records_data = document.get("patches")
    if not isinstance(records_data, list) or not records_data:
        raise ContractError("patches must be a non-empty list")
    if not isinstance(series_data.get("ordered_patch_ids"), list):
        raise ContractError("ordered_patch_ids must be a list")
    ordered_ids = series_data["ordered_patch_ids"]
    if any(not isinstance(item, str) or not item for item in ordered_ids):
        raise ContractError("ordered patch IDs must be non-empty strings")

    records_by_id: dict[str, dict] = {}
    for raw_record in records_data:
        record = _mapping(raw_record, "patch record")
        patch_id = record.get("id")
        if not isinstance(patch_id, str) or not patch_id or patch_id in records_by_id:
            raise ContractError("patch IDs must be unique non-empty strings")
        records_by_id[patch_id] = record
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(records_by_id):
        raise ContractError("the public series must order every patch exactly once")

    source_commit = series_data.get("source_commit")
    if source_commit != LOCKED_SOURCE_COMMIT:
        raise ContractError("public patch source commit is not the locked CoreMark source")
    if series_data.get("id") != "coremark-k3-x100":
        raise ContractError("public patch series ID is invalid")

    resolved: list[PatchRecord] = []
    for patch_id in ordered_ids:
        record = records_by_id[patch_id]
        path_text = record.get("file")
        digest = record.get("patch_sha256")
        if not isinstance(path_text, str) or SHA256_RE.fullmatch(str(digest)) is None:
            raise ContractError(f"patch path or digest is invalid: {patch_id}")
        pure_path = PurePosixPath(path_text)
        if pure_path.is_absolute() or ".." in pure_path.parts or pure_path.parts[:1] != (
            "patches",
        ):
            raise ContractError(f"patch path is unsafe: {path_text}")
        if (
            record.get("source_base_commit") != LOCKED_SOURCE_COMMIT
            or record.get("class") != "k3-native-upstream-port"
            or record.get("source_lane") != "official-score"
            or record.get("result_mode") != "best-achievable"
            or record.get("applies_to") != ["k3-development"]
            or set(record.get("forbidden_tracks", []))
            != {"rpi-native", "k3-compatible"}
            or record.get("upstream_status") != "upstream-ready-not-submitted"
        ):
            raise ContractError(f"patch publication classification is invalid: {patch_id}")
        resolved_record = PatchRecord(patch_id, Path(path_text), str(digest))
        patch_path = resolved_record.absolute_path(repository_root)
        if hashlib.sha256(patch_path.read_bytes()).hexdigest() != digest:
            raise ContractError(f"patch SHA256 mismatch: {patch_id}")
        resolved.append(resolved_record)

    series_bytes = "".join(
        f"{record.patch_id}|{record.sha256}\n" for record in resolved
    ).encode()
    actual_series_digest = hashlib.sha256(series_bytes).hexdigest()
    if (
        series_data.get("series_sha256") != actual_series_digest
        or SHA256_RE.fullmatch(actual_series_digest) is None
    ):
        raise ContractError("patch series SHA256 mismatch")
    return PatchSeries(
        series_id=str(series_data["id"]),
        source_commit=source_commit,
        series_sha256=actual_series_digest,
        patches=tuple(resolved),
    )


def public_patch_series() -> PatchSeries:
    return load_patch_series()


def load_toolchain_lock(path: Path = ENVIRONMENT_LOCK) -> ToolchainLock:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load toolchain lock: {path}") from error
    document = _mapping(document, "toolchain lock")
    toolchains = _mapping(document.get("toolchains"), "toolchain locks")
    x100 = _mapping(toolchains.get("k3_x100_clang_23"), "K3 X100 toolchain lock")
    llvm = _mapping(x100.get("llvm"), "LLVM lock")
    package = _mapping(x100.get("apt_package"), "APT package lock")
    lock = ToolchainLock(
        package_name=str(package.get("name", "")),
        package_version=str(package.get("version", "")),
        architecture=str(package.get("architecture", "")),
        package_sha256=str(package.get("sha256", "")),
        packages_index_sha256=str(package.get("packages_index_sha256", "")),
        compiler_path=Path(str(package.get("installed_compiler", ""))),
        compiler_sha256=str(package.get("installed_compiler_sha256", "")),
        llvm_commit=str(llvm.get("commit", "")),
    )
    expected = {
        "package_name": "k3-coremark-clang-23-x100",
        "package_version": "23.0.0~git20260713+a0df86d-1",
        "architecture": "riscv64",
        "package_sha256": "ee1c4675f8d2eb0bbf75414704d1901ec98b918db6c3519bcbc2679c575e2cc6",
        "packages_index_sha256": "c9a38c330f8695a45fe0667ec95544d0e239d6d712ddc258a28669f6870a0199",
        "compiler_sha256": "6f146e285beff9b1a4ed0b515d51ea953935e0b03669f52d77faea2992ed59a8",
        "llvm_commit": "a0df86deb4295ff9ebebe54eb515bc49a7fb65f8",
    }
    for field, value in expected.items():
        if getattr(lock, field) != value:
            raise ContractError(f"toolchain lock {field} mismatch")
    if not lock.compiler_path.is_absolute():
        raise ContractError("toolchain compiler path must be absolute")
    return lock


def load_clang_pgo_lock(path: Path = ENVIRONMENT_LOCK) -> ClangPgoLock:
    """Load the reviewed Clang 23 + X100 + LLVM PGO lane lock."""
    from .clang_pgo import ClangPgoLock

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load clang PGO lock: {path}") from error
    document = _mapping(document, "clang PGO document")
    toolchains = _mapping(document.get("toolchains"), "toolchain locks")
    lane = _mapping(toolchains.get("k3_x100_clang_23_pgo"), "Clang 23 PGO lane")
    host = _mapping(lane.get("host_package"), "Clang 23 host package")
    target = _mapping(lane.get("target"), "Clang 23 target")
    runtime = _mapping(lane.get("profile_runtime"), "Clang 23 profile runtime")
    profile = _mapping(lane.get("profile_data"), "Clang 23 profile data")

    lock = ClangPgoLock(
        package_version=str(host.get("package_version", "")),
        version_token=str(host.get("version_token", "")),
        compiler_path=Path(str(host.get("compiler", ""))),
        compiler_sha256=str(host.get("compiler_sha256", "")),
        triple=str(target.get("triple", "")),
        sysroot=Path(str(target.get("sysroot", ""))),
        gcc_toolchain=Path(str(target.get("gcc_toolchain", ""))),
        abi=str(target.get("abi", "")),
        cpu_model=str(target.get("cpu_model", "")),
        port_flags=str(lane.get("port_flags", "")),
        profile_runtime_path=Path(str(runtime.get("path", ""))),
        profile_runtime_sha256=str(runtime.get("sha256", "")),
        profile_runtime_commit=str(runtime.get("commit", "")),
        profile_data_path=Path(str(profile.get("path", ""))),
        profile_data_sha256=str(profile.get("sha256", "")),
    )
    for name in (
        "package_version",
        "version_token",
        "triple",
        "abi",
        "cpu_model",
        "port_flags",
        "profile_runtime_commit",
    ):
        if not getattr(lock, name):
            raise ContractError(f"clang PGO lock {name} is required")
    for name in ("compiler_sha256", "profile_runtime_sha256", "profile_data_sha256"):
        if SHA256_RE.fullmatch(getattr(lock, name)) is None:
            raise ContractError(f"clang PGO lock {name} must be a SHA256")
    for name in ("compiler_path", "sysroot", "gcc_toolchain", "profile_runtime_path", "profile_data_path"):
        if not getattr(lock, name).is_absolute():
            raise ContractError(f"clang PGO lock {name} must be an absolute path")
    return lock


def expected_runtime_profile_digest(track: str, path: Path = ENVIRONMENT_LOCK) -> str:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load environment lock: {path}") from error
    profiles = _mapping(_mapping(document, "environment lock").get("runtime_profiles"), "runtime profiles")
    profile = _mapping(profiles.get(track), f"runtime profile {track}")
    digest = profile.get("foundation_profile_sha256")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise ContractError(f"runtime profile digest is invalid for {track}")
    return digest


def expected_runtime_architecture(track: str, path: Path = ENVIRONMENT_LOCK) -> str:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"cannot load environment lock: {path}") from error
    profiles = _mapping(
        _mapping(document, "environment lock").get("runtime_profiles"),
        "runtime profiles",
    )
    profile = _mapping(profiles.get(track), f"runtime profile {track}")
    architecture = profile.get("architecture")
    if architecture not in {"aarch64", "riscv64"}:
        raise ContractError(f"runtime profile architecture is invalid for {track}")
    return str(architecture)


def _patch(source_root: Path, patch_path: Path, *mode: str) -> None:
    content = patch_path.read_bytes()
    for dry_run in (True, False):
        command = ["patch", "--batch", *mode, "--fuzz=0"]
        if dry_run:
            command.append("--dry-run")
        command.extend(["-d", str(source_root), "-p1"])
        completed = subprocess.run(command, input=content, capture_output=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.decode(errors="replace").strip()
            raise ContractError(f"zero-fuzz patch command failed: {patch_path.name}: {detail}")


def apply_patch_series(
    source_root: Path, series: PatchSeries, repository_root: Path = PROJECT_ROOT
) -> None:
    applied: list[PatchRecord] = []
    try:
        for record in series.patches:
            _patch(source_root, record.absolute_path(repository_root), "--forward")
            applied.append(record)
    except ContractError:
        for record in reversed(applied):
            _patch(source_root, record.absolute_path(repository_root), "--reverse")
        raise


def reverse_patch_series(
    source_root: Path, series: PatchSeries, repository_root: Path = PROJECT_ROOT
) -> None:
    for record in reversed(series.patches):
        _patch(source_root, record.absolute_path(repository_root), "--reverse")
