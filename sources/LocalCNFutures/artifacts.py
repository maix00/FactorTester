"""Derived-artifact adapter for the LocalCNFutures data source."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sources.LocalCNFutures import ROLLER_INFO_PATH, SOURCE_DATA_DIR, TERM_STRUCTURE_PATH
from tools.data.artifacts import ArtifactCoverage, DerivedArtifactSpec, register_artifact
from tools.products.AdjustableTermStructure import (
    TERM_CONTRACT_UID_COL,
    TERM_PRODUCT_COL,
    TERM_TRADING_DAY_COL,
)


PROVIDER = "LocalCNFutures"
CONTINUOUS_KEY = f"{PROVIDER}:continuous_contracts:primary_secondary"
TERM_STRUCTURE_KEY = f"{PROVIDER}:term_structure:listed_contracts"


def _continuous_coverage(path: Path):
    frame = pd.read_parquet(path, columns=["PRODUCT", "CONTRACT_UID", "STARTDATE", "ENDDATE"])
    frame["variant"] = frame["PRODUCT"].astype(str).str.contains(r"(?:_S|-S)\.", regex=True).map(
        {False: "primary", True: "secondary"}
    )
    frame["product_name"] = frame["PRODUCT"].astype(str).str.replace(
        r"(?:_S|-S)(?=\.)", "", regex=True
    )
    for (product_name, variant), rows in frame.groupby(["product_name", "variant"]):
        yield ArtifactCoverage(
            str(product_name),
            variant=str(variant),
            start_value=str(pd.to_datetime(rows["STARTDATE"]).min().date()),
            end_value=str(pd.to_datetime(rows["ENDDATE"]).max().date()),
            row_count=len(rows),
            entity_count=rows["CONTRACT_UID"].nunique(),
        )


def _term_structure_coverage(path: Path):
    frame = pd.read_parquet(
        path,
        columns=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL],
    )
    for product_name, rows in frame.groupby(TERM_PRODUCT_COL):
        yield ArtifactCoverage(
            str(product_name),
            variant="listed_contracts",
            start_value=str(pd.to_datetime(rows[TERM_TRADING_DAY_COL]).min().date()),
            end_value=str(pd.to_datetime(rows[TERM_TRADING_DAY_COL]).max().date()),
            row_count=len(rows),
            entity_count=rows[TERM_CONTRACT_UID_COL].nunique(),
        )


def _build_continuous(staging: Path) -> None:
    from .scripts.generate_main import generate_main_contract_series

    generate_main_contract_series(
        roller_info_path=str(staging),
        rebuild_minute_product=False,
        rebuild_roller_info=True,
    )
    staging_csv = staging.with_suffix(".csv")
    if staging_csv.exists():
        staging_csv.unlink()


def _build_term_structure(staging: Path) -> None:
    from .scripts.generate_term_structure import generate_cn_futures_term_structure

    generate_cn_futures_term_structure(output_path=str(staging))


def _invalidate_continuous(path: Path) -> None:
    from tools.data.hub import DataHub
    from .CNFutures import _CNFUTURES_BY_NAME

    DataHub.get_instance().invalidate("roller_info", str(path))
    for product in {id(item): item for item in _CNFUTURES_BY_NAME.values()}.values():
        product.roller_info = None


def _invalidate_term_structure(path: Path) -> None:
    from tools.products.AdjustableTermStructure import invalidate_term_structure_path

    invalidate_term_structure_path(str(path))


def register_local_cn_futures_artifacts() -> tuple[DerivedArtifactSpec, DerivedArtifactSpec]:
    root = Path(SOURCE_DATA_DIR)
    continuous = register_artifact(DerivedArtifactSpec(
        provider=PROVIDER,
        name="continuous_contracts",
        variant="primary_secondary",
        output_path=Path(ROLLER_INFO_PATH),
        source_paths=(root / "wind_mapping.parquet", root / "data_dayk.parquet"),
        build=_build_continuous,
        coverage=_continuous_coverage,
        schema_version="1",
        accept_unmanaged_existing=True,
        on_published=_invalidate_continuous,
    ))
    term_structure = register_artifact(DerivedArtifactSpec(
        provider=PROVIDER,
        name="term_structure",
        variant="listed_contracts",
        output_path=Path(TERM_STRUCTURE_PATH),
        source_paths=(root / "data_dayk.parquet", Path(ROLLER_INFO_PATH)),
        dependencies=(continuous.key,),
        build=_build_term_structure,
        coverage=_term_structure_coverage,
        schema_version="4-listed-contracts-settlement-vwap",
        accept_unmanaged_existing=False,
        on_published=_invalidate_term_structure,
    ))
    return continuous, term_structure


ARTIFACTS = register_local_cn_futures_artifacts()
