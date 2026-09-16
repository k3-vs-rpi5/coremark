from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from coremark_project.manifests import (
    ContractError,
    apply_patch_series,
    load_clang_pgo_lock,
    load_patch_series,
    load_toolchain_lock,
    reverse_patch_series,
)

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "patches/manifest.yaml"


def test_clang_pgo_lane_identity_is_pinned() -> None:
    lock = load_clang_pgo_lock()

    assert lock.package_version == (
        "1:23.1.2~++20260910044232+069ef0e7cb36-1~exp1~20260910044242.70"
    )
    assert lock.compiler_sha256 == (
        "17446adf0658fa412c98cbb304a9cad58a8a66faf78bac797836655a3ac0e6e4"
    )
    assert lock.triple == "riscv64-unknown-linux-gnu"
    assert lock.abi == "lp64d"
    assert lock.cpu_model == "spacemit-x100"
    assert lock.profile_runtime_commit == "069ef0e7cb36"
    assert lock.profile_runtime_sha256 == (
        "979daeff172b683af92089638cf0d11dab11cc65fa4915ddd1b0de45752d7927"
    )
    assert lock.profile_data_sha256 == (
        "77dfeb561fe296978fb340dd92af13da7a031516e5b15b4b21c6c00668cf079d"
    )
    for path in (
        lock.compiler_path,
        lock.sysroot,
        lock.gcc_toolchain,
        lock.profile_runtime_path,
        lock.profile_data_path,
    ):
        assert path.is_absolute()


def test_locked_patch_and_toolchain_identities_resolve_inside_project(
    tmp_path: Path,
) -> None:
    series = load_patch_series(MANIFEST, PROJECT)
    toolchain = load_toolchain_lock()

    assert series.source_commit == "b56889a7bd9d5624fbeff2a73ba69878e6a9c146"
    assert [record.patch_id for record in series.patches] == [
        "0001-ports-add-linux-clang-port-for-spacemit-x100"
    ]
    assert all(record.absolute_path(PROJECT).is_file() for record in series.patches)
    assert toolchain.package_version == "23.0.0~git20260713+a0df86d-1"
    assert toolchain.compiler_sha256 == (
        "6f146e285beff9b1a4ed0b515d51ea953935e0b03669f52d77faea2992ed59a8"
    )

    (tmp_path / "linux-spacemit-x100").mkdir()
    apply_patch_series(tmp_path, series, PROJECT)
    added = tmp_path / "linux-spacemit-x100/core_portme.mak"
    assert added.is_file()
    reverse_patch_series(tmp_path, series, PROJECT)
    assert not added.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["public_delivery_series"].update(source_commit="0" * 40),
        lambda data: data["patches"][0].update(file="../outside.patch"),
        lambda data: data["patches"][0].update(patch_sha256="0" * 64),
        lambda data: data["patches"].append(deepcopy(data["patches"][0])),
    ],
)
def test_patch_manifest_rejects_untrusted_identity(tmp_path: Path, mutation) -> None:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mutation(data)
    candidate = tmp_path / "manifest.yaml"
    candidate.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError):
        load_patch_series(candidate, PROJECT)
