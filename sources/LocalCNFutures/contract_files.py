"""Cross-platform contract parquet filename handling."""

from __future__ import annotations

from pathlib import Path


EXCHANGE_SHORT_TO_ID = {
    "DCE": "DCE",
    "CZC": "CZCE",
    "INE": "INE",
    "SHF": "SHFE",
    "CFE": "CFFEX",
    "GFE": "GFEX",
}


def portable_contract_filename(alias: str, suffix: str = ".parquet") -> str:
    """Return the Windows-safe filename used for newly generated data."""
    return f"{str(alias).replace('|', '_')}{suffix}"


def resolve_contract_parquet_path(folder: str | Path, alias: str) -> Path:
    """Return the canonical cross-platform path for a contract."""
    return Path(folder) / portable_contract_filename(alias)


def contract_alias_from_path(path: str | Path) -> str:
    return Path(path).stem.replace("_", "|")


def split_contract_product_month(product_month: str) -> tuple[str, str]:
    """Split exchange contract code into ``(product_id, contract_code)``.

    The contract code is intentionally "the rest after the first digit" so
    DCE month-average futures such as ``L2602F`` keep the ``2602F`` suffix.
    """

    text = str(product_month).strip().upper()
    first_digit = next((idx for idx, char in enumerate(text) if char.isdigit()), len(text))
    if first_digit == len(text):
        raise ValueError(f"contract code has no contract month: {product_month!r}")
    return text[:first_digit], text[first_digit:]


def contract_uid_from_exchange_contract(contract: str) -> str:
    """Convert ``L2602F.DCE``/``LC2605.GFE`` to Local contract UID."""

    text = str(contract).strip().upper()
    if "." not in text:
        raise ValueError(f"contract must include exchange suffix: {contract!r}")
    product_month, exchange_short = text.rsplit(".", 1)
    product_id, contract_code = split_contract_product_month(product_month)
    exchange_id = EXCHANGE_SHORT_TO_ID.get(exchange_short, exchange_short)
    return f"{exchange_id}|F|{product_id}|{contract_code}"
