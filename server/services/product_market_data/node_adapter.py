"""Node-local compatibility adapter for the existing source-owned chart reader."""
from server.services.product_market_data import price_series


def read_installed_market(*, offer, query):
    from sources.registry import installed_bundles
    from traderesearch_data.bundles import bundle_content_fingerprint
    bundles = [item for item in installed_bundles() if item.bundle_id == offer.installation.bundle_id]
    if (len(bundles) != 1 or bundles[0].version != offer.installation.bundle_version
            or bundle_content_fingerprint(bundles[0]) != offer.installation.bundle_fingerprint):
        raise ValueError("installed Bundle version differs from selected input")
    if not any(member.id == offer.member_id for member in bundles[0].members):
        raise ValueError("selected member is not installed")
    # These existing readers retain their shared-cache admission and bounded
    # Parquet projection/aggregation. Manager never imports this adapter.
    payload = {**query, "data_source": offer.member_id}
    if "|" in offer.product_ref:
        payload["contract_uid"] = offer.product_ref
    else:
        payload["product_name"] = offer.product_ref
    return price_series(payload)
