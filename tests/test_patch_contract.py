from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from coremark_project.manifests import (
    ContractError,
    apply_patch_series,
    load_patch_series,
    load_toolchain_lock,
    reverse_patch_series,
)

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "patches/manifest.yaml"


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
