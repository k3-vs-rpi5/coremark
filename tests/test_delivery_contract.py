from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest
from coremark_project.delivery import (
    PROJECT_ROOT,
    ContractError,
    ResultMode,
    RunMode,
    RunRequest,
    Track,
    _execution_plan,
    _sample_command,
    _seal_failed_run,
    parse_official_output,
    prepare_run_request,
)

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = PROJECT.parent.parent / ".local-test-evidence"


def test_execution_plan_validates_before_warmup_and_measurement() -> None:
    plan = _execution_plan(RunMode.FORMAL)
    assert plan[0] == ("validation", 3, 30, True)
    assert plan[1] == ("performance", 1, 3, False)
    assert plan[2] == ("performance", 3, 30, True)


def test_failed_run_is_retained_as_checksum_sealed_non_public_evidence(
    tmp_path: Path,
) -> None:
    out_root = tmp_path / "failed-run"
    out_root.mkdir()
    (out_root / "partial.log").write_text("partial\n", encoding="utf-8")

    _seal_failed_run(out_root, ContractError("CRC mismatch"))

    manifest = (out_root / "manifest.yaml").read_text(encoding="utf-8")
    assert "status: invalid" in manifest
    assert "public_claim: false" in manifest
    assert "CRC mismatch" in manifest
    assert (out_root / "SHA256SUMS").is_file()


def test_track_rejects_a_host_with_the_wrong_cpu_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    with pytest.raises(ContractError, match="requires host architecture aarch64"):
        prepare_run_request(
            work_root=tmp_path / "build",
            evidence_root=tmp_path / "evidence",
            out_dir=tmp_path / "evidence/run",
            track=Track.RPI_NATIVE,
            result_mode=ResultMode.DEFAULT_PARITY,
            run_mode=RunMode.QUICK,
            cpu_set="0",
            runtime_profile_digest=(
                "981a9ce13ece47b1ba8a0504a7e7f4afb3b4bcaae720a45b40dd178ac11bd727"
            ),
        )


def test_project_exposes_only_two_path_independent_shell_entries() -> None:
    assert PROJECT_ROOT == PROJECT
    scripts = sorted(path.name for path in (PROJECT / "scripts").glob("*.sh"))
    assert scripts == ["build.sh", "run.sh"]
    for name in scripts:
        path = PROJECT / "scripts" / name
        assert path.stat().st_mode & 0o111
        text = path.read_text(encoding="utf-8")
        assert "coremark_project.cli" in text
        assert "cpu-foundation" not in text
        completed = subprocess.run(
            [str(path), "--help"],
            cwd=PROJECT,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("out_dir", "cpu_set", "digest"),
    [
        (PROJECT / "tracked-output", "0", "a" * 64),
        (EVIDENCE_ROOT / "run", "--cpu", "a" * 64),
        (EVIDENCE_ROOT / "run", "0", "A" * 64),
    ],
)
def test_run_request_rejects_uncontrolled_output_or_identity(
    out_dir: Path,
    cpu_set: str,
    digest: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "riscv64")
    with pytest.raises(ContractError):
        prepare_run_request(
            work_root=EVIDENCE_ROOT / "build",
            evidence_root=EVIDENCE_ROOT,
            out_dir=out_dir,
            track=Track.K3_DEVELOPMENT,
            result_mode=ResultMode.BEST_ACHIEVABLE,
            run_mode=RunMode.QUICK,
            cpu_set=cpu_set,
            runtime_profile_digest=digest,
        )


@pytest.mark.parametrize(
    ("mode", "crcs"),
    [
        ("performance", ("0xe9f5", "0xe714", "0x1fd7", "0x8e3a")),
        ("validation", ("0x18f2", "0xe3c1", "0x0747", "0x8d84")),
    ],
)
def test_official_output_enforces_crc_and_minimum_duration(mode: str, crcs: tuple[str, ...]) -> None:
    seed, list_crc, matrix_crc, state_crc = crcs
    output = "\n".join(
        [
            "CoreMark 1.0",
            "Total time (secs): 10.25",
            "Iterations/Sec : 18311.7",
            f"seedcrc          : {seed}",
            f"[0]crclist       : {list_crc}",
            f"[0]crcmatrix     : {matrix_crc}",
            f"[0]crcstate      : {state_crc}",
            "[0]crcfinal      : 0xabcd",
            "Correct operation validated.",
        ]
    )
    assert parse_official_output(mode, output).iterations_per_second == 18311.7
    with pytest.raises(ContractError, match="below 10 seconds"):
        parse_official_output(mode, output.replace("10.25", "9.99"))


def test_compatible_track_executes_inside_the_locked_rootfs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs = tmp_path / "rootfs"
    binary_dir = tmp_path / "build/bin"
    rootfs.mkdir()
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "coremark-performance.exe"
    monkeypatch.setenv("COREMARK_ROOTFS", str(rootfs))
    request = RunRequest(
        work_root=tmp_path / "build",
        evidence_root=tmp_path / "evidence",
        out_dir=tmp_path / "evidence/run",
        track=Track.K3_COMPATIBLE,
        result_mode=ResultMode.DEFAULT_PARITY,
        run_mode=RunMode.QUICK,
        cpu_set="0",
        runtime_profile_digest="a" * 64,
    )

    command = _sample_command(request, binary, "performance")
    assert command[:8] == [
        "taskset",
        "-c",
        "0",
        "bwrap",
        "--ro-bind",
        str(rootfs),
        "/",
        "--dev",
    ]
    assert command[-5:] == [
        "/tmp/coremark-bin/coremark-performance.exe",
        "0",
        "0",
        "0x66",
        "0",
    ]
