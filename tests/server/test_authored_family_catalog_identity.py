"""Current metadata heads use factor_id, not the old presentation name field."""
import pytest
from server.manager.services.client_factor_catalog import ClientFactorCatalogMixin

@pytest.mark.parametrize('summary',[
    {'factor_id':'CreatedFamily','factor_name':'Display family'},
    {'id':'CreatedFamily','name':'Display family'},
])
def test_own_family_is_visible_before_any_parameterized_factor(monkeypatch,summary):
    monkeypatch.setattr('server.modules.custom_factors.catalog.list_custom_factors',lambda owner:[summary])
    result=ClientFactorCatalogMixin._custom_source_families('alice','Alice')
    assert len(result)==1
    assert result[0]['factor_family_alias']=='CreatedFamily'
    assert result[0]['factor_family_name']=='Display family'
    assert result[0]['owner_username']=='alice'
    assert result[0]['owner_alias']=='Alice'
    assert result[0]['factor_count']==0


def test_missing_family_identity_is_not_replaced_with_a_display_label(monkeypatch):
    monkeypatch.setattr('server.modules.custom_factors.catalog.list_custom_factors',lambda owner:[{'description':'invalid'}])
    assert ClientFactorCatalogMixin._custom_source_families('alice')==[]
