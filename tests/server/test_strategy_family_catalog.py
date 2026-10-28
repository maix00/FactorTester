from server.services.strategy_family_catalog import (
    list_public_strategy_families, strategy_family,
)


def test_public_strategy_families_are_owned_by_tradresearch():
    families = {item["family_id"]: item for item in list_public_strategy_families()}
    assert families["threshold"]["name"] == "因子阈值策略家族"
    assert families["cross_sectional_group"]["name"] == "因子分组第N组策略家族"
    assert strategy_family("threshold")["parameters"] == [
        "entry_threshold", "exit_threshold", "side_mode",
    ]


def test_nautilus_catalog_is_compatibility_shim():
    from server.services.nautilus_bridge.strategy_family_catalog import (
        list_public_strategy_families as shim,
    )

    assert shim() == list_public_strategy_families()
