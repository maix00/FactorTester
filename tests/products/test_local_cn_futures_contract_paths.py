from pathlib import Path

from sources.LocalCNFutures.CNFutures import _contract_data_path


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
