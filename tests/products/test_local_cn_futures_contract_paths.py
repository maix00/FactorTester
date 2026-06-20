from pathlib import Path

from sources.LocalCNFutures.CNFutures import _contract_data_path
from sources.LocalCNFutures.contract_files import (
    contract_alias_from_path,
    portable_contract_filename,
    resolve_contract_parquet_path,
)


def test_contract_data_path_reads_legacy_pipe_filename(tmp_path: Path):
    legacy_path = tmp_path / "GFEX|F|PT|2606.parquet"
    legacy_path.touch()

    assert _contract_data_path(str(tmp_path), "GFEX|F|PT|2606") == str(legacy_path)


def test_contract_data_path_reads_windows_safe_filename(tmp_path: Path):
    safe_path = tmp_path / "GFEX_F_PT_2606.parquet"
    safe_path.touch()

    assert _contract_data_path(str(tmp_path), "GFEX|F|PT|2606") == str(safe_path)


def test_contract_data_path_prefers_windows_safe_filename(tmp_path: Path):
    legacy_path = tmp_path / "GFEX|F|PT|2606.parquet"
    safe_path = tmp_path / "GFEX_F_PT_2606.parquet"
    legacy_path.touch()
    safe_path.touch()

    assert _contract_data_path(str(tmp_path), "GFEX|F|PT|2606") == str(safe_path)


def test_contract_file_helpers_share_portable_and_legacy_semantics(tmp_path: Path):
    alias = "DCE|F|BZ|2603"
    legacy_path = tmp_path / f"{alias}.parquet"
    legacy_path.touch()

    assert portable_contract_filename(alias) == "DCE_F_BZ_2603.parquet"
    assert resolve_contract_parquet_path(tmp_path, alias) == legacy_path
    assert contract_alias_from_path(legacy_path) == alias
    assert contract_alias_from_path(tmp_path / portable_contract_filename(alias)) == alias
