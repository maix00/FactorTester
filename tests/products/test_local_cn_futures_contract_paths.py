from pathlib import Path

from sources.LocalCNFutures.CNFutures import _contract_data_path
from sources.LocalCNFutures.contract_files import (
    contract_alias_from_path,
    portable_contract_filename,
    resolve_contract_parquet_path,
    split_contract_product_month,
)


def test_contract_data_path_reads_canonical_filename(tmp_path: Path):
    safe_path = tmp_path / "GFEX_F_PT_2606.parquet"
    safe_path.touch()

    assert _contract_data_path(str(tmp_path), "GFEX|F|PT|2606") == str(safe_path)


def test_contract_file_helpers_use_only_canonical_semantics(tmp_path: Path):
    alias = "DCE|F|BZ|2603"
    canonical_path = tmp_path / portable_contract_filename(alias)

    assert portable_contract_filename(alias) == "DCE_F_BZ_2603.parquet"
    assert resolve_contract_parquet_path(tmp_path, alias) == canonical_path
    assert contract_alias_from_path(canonical_path) == alias


def test_contract_file_helpers_keep_alpha_contract_suffix(tmp_path: Path):
    alias = "DCE|F|L|2605F"
    canonical_path = tmp_path / portable_contract_filename(alias)

    assert split_contract_product_month("L2605F") == ("L", "2605F")
    assert portable_contract_filename(alias) == "DCE_F_L_2605F.parquet"
    assert resolve_contract_parquet_path(tmp_path, alias) == canonical_path
    assert contract_alias_from_path(canonical_path) == alias
