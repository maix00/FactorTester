"""Source substitution must preserve semantics and explicit execution identity."""
from dataclasses import replace

import pytest

from traderesearch_data.execution import (
    BarOffer, BarRequirement, BundleInstallation, ServiceDeployment,
    bind_bar_input, compatible_bar_offers,
)


def _requirement():
    return BarRequirement("T.CFE", "1-MINUTE-LAST-EXTERNAL", "raw", "end-inclusive-v1",
                          ("open", "high", "low", "close", "volume"), 100, 200)


def _offer(node="node-b", installation="local-data"):
    bundle = BundleInstallation("manager-a", node, installation, "cn-data", "1",
                                "sha256:" + "a" * 64, "platform")
    return BarOffer(bundle, "minute", "T.CFE", "1-MINUTE-LAST-EXTERNAL", "raw",
                    "end-inclusive-v1", _requirement().fields, 0, 300, True)


def _target(node="node-b"):
    return ServiceDeployment("manager-a", node, "tests", "build-1", ("backtest",))


def test_node_installations_are_distinct_while_requirement_is_portable():
    first, second = _offer(), _offer("node-c")
    assert first.source_ref != second.source_ref
    assert first.installation.bundle_id == second.installation.bundle_id
    for offer in (first, second):
        requirement = _requirement()
        bound = bind_bar_input(requirement, _target(offer.installation.node_id),
                               test_type="backtest", offers=(first, second),
                               selected_source_ref=offer.source_ref)
        assert bound.requirement.requirement_ref == requirement.requirement_ref
    assert _offer(installation="another-copy").source_ref != first.source_ref


def test_installation_identity_survives_upgrade_but_frozen_binding_rejects_it():
    offer = _offer()
    bound = bind_bar_input(_requirement(), _target(), test_type="backtest",
                           offers=(offer,), selected_source_ref=offer.source_ref)
    upgraded = replace(offer, installation=replace(offer.installation, bundle_version="2"))
    assert upgraded.source_ref == offer.source_ref
    with pytest.raises(ValueError, match="installation changed"):
        bound.revalidate(_target(), upgraded)
    with pytest.raises(ValueError, match="deployment changed"):
        bound.revalidate(replace(_target(), deployment_ref="build-2"), offer)
    bound.revalidate(_target(), replace(offer, coverage_end_ns=400))


@pytest.mark.parametrize("changes", [
    {"price_basis": "back-adjusted"}, {"time_semantics": "start-exclusive-v1"},
    {"bar_spec": "1-MINUTE-BID-EXTERNAL"}, {"product_ref": "TL.CFE"},
    {"fields": ("close",)}, {"coverage_start_ns": 101},
    {"coverage_end_ns": 199}, {"coverage_start_ns": None, "coverage_end_ns": None},
    {"available": False},
])
def test_equal_display_frequency_is_insufficient_for_substitution(changes):
    offer = replace(_offer(), **changes)
    assert compatible_bar_offers(_requirement(), _target(), (offer,)) == ()


def test_explicit_selection_never_substitutes_another_node_or_source():
    first, other = _offer(), _offer("node-c")
    with pytest.raises(ValueError, match="missing, ambiguous"):
        bind_bar_input(_requirement(), _target(), test_type="backtest", offers=(other,),
                       selected_source_ref=first.source_ref)
    with pytest.raises(ValueError, match="ambiguous"):
        bind_bar_input(_requirement(), _target(), test_type="backtest", offers=(first, first),
                       selected_source_ref=first.source_ref)
    with pytest.raises(ValueError, match="test type"):
        bind_bar_input(_requirement(), _target(), test_type="paper", offers=(first,),
                       selected_source_ref=first.source_ref)


def test_requirement_field_order_does_not_change_identity():
    requirement = _requirement()
    assert replace(requirement, fields=tuple(reversed(requirement.fields))).requirement_ref == requirement.requirement_ref
    assert replace(requirement, end_ns=201).requirement_ref != requirement.requirement_ref
    assert replace(requirement, end_ns=201).equivalence_ref == requirement.equivalence_ref


@pytest.mark.parametrize("changes", [{"start_ns": 201}, {"end_ns": True},
                                    {"fields": ("close", "close")}, {"bar_spec": ""}])
def test_invalid_requirement_is_rejected_at_planning(changes):
    with pytest.raises(ValueError):
        replace(_requirement(), **changes)


def test_projection_from_other_authority_cannot_bind_to_same_node_name():
    first = _offer()
    foreign = replace(first, installation=replace(first.installation, authority="manager-z"))
    assert compatible_bar_offers(_requirement(), _target(), (foreign,)) == ()
    assert first.source_ref != foreign.source_ref
