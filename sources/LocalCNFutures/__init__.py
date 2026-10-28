"""Local Chinese-futures Bundle; resolve data paths only when requested."""
from __future__ import annotations

__all__ = ["SOURCE_DATA_DIR", "ROLLER_INFO_PATH", "MINK_PRODUCT_DIR", "TERM_STRUCTURE_PATH"]


def __getattr__(name: str) -> str:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from scripts.data_dir import DATA_DIR
    from tools.data.artifacts.storage import artifact_path, source_data_root

    # Resolve only the requested path. Do not probe or open any source data.
    if name == "SOURCE_DATA_DIR":
        value = str(source_data_root("LocalCNFutures", default=DATA_DIR))
    elif name == "MINK_PRODUCT_DIR":
        value = __getattr__("SOURCE_DATA_DIR") + "/data_mink_product"
    else:
        filename = {"ROLLER_INFO_PATH": "roller_info.parquet",
                    "TERM_STRUCTURE_PATH": "term_structure-listed_contracts.parquet"}[name]
        value = str(artifact_path("LocalCNFutures", filename))
    globals()[name] = value
    return value
