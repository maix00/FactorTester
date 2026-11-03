"""Catalog paging must bound metadata projection before rendering leaves."""
from types import SimpleNamespace
import pytest
from server.manager.services.client_product_catalog import ClientProductCatalogMixin

@pytest.fixture
def directory(monkeypatch):
    from server.modules.products import product_category_views
    from server.modules.shared import price_services
    from server.services import product_catalog_projection,product_tree
    from tools.products import classifier_paths
    rows=[SimpleNamespace(name=f'P{i:05d}',code=str(i),exchange='TEST') for i in range(5000)]
    calls=[]
    monkeypatch.setattr(product_category_views,'tree_for_path',lambda *a,**k:({},''))
    monkeypatch.setattr(product_category_views,'category_products_for_path',lambda *a,**k:None)
    monkeypatch.setattr(price_services,'cached_contracts',lambda:rows)
    monkeypatch.setattr(price_services,'available_sources_for_product',lambda p:calls.append(p.name) or [{'alias':'source'}])
    monkeypatch.setattr(product_catalog_projection,'catalog_product_description',lambda p,name:name)
    monkeypatch.setattr(product_catalog_projection,'source_family_ids_for_member_ids',lambda refs:('family',))
    monkeypatch.setattr(classifier_paths,'classifier_object_path',lambda p:'Product/'+p.name)
    return calls

def test_unsearched_tree_projects_only_requested_page(directory):
    result=ClientProductCatalogMixin.contract_tree_page(page=3,limit=25)
    assert result['total']==5000 and result['total_pages']==200 and result['has_more']
    assert len(result['nodes'])==25
    assert [row['product_name'] for row in result['nodes']]==[f'P{i:05d}' for i in range(50,75)]
    assert len(directory)==25

def test_tree_search_still_matches_source_metadata(directory):
    result=ClientProductCatalogMixin.contract_tree_page(query='source',page=2,limit=25)
    assert result['total']==5000 and len(result['nodes'])==25
    assert result['nodes'][0]['product_name']=='P00025'

def test_empty_out_of_range_page_does_not_project_metadata(directory):
    result=ClientProductCatalogMixin.contract_tree_page(page=1000,limit=25)
    assert result['nodes']==[] and result['total']==5000
    assert directory==[]

def test_warm_search_reuses_metadata_and_empty_scope_does_not_fall_back(directory):
    ClientProductCatalogMixin.contract_tree_page(query='source',page=1,limit=25)
    assert len(directory)==5000
    ClientProductCatalogMixin.contract_tree_page(query='source',page=2,limit=25)
    assert len(directory)==5000
    result=ClientProductCatalogMixin.contract_tree_page(source_ids=(),page=1,limit=25)
    assert result['total']==0 and result['nodes']==[]


def test_explicit_catalog_search_includes_non_contract_products(directory, monkeypatch):
    from server.modules.products import product_category_views
    from server.modules.shared import price_services
    rows = price_services.cached_contracts()
    monkeypatch.setattr(price_services, 'cached_contracts', lambda: ())
    monkeypatch.setattr(product_category_views, 'tree_for_path', lambda *a, **k: (
        {'Product': {'$OBJECTS$': rows}}, '',
    ))
    result = ClientProductCatalogMixin.contract_tree_page(catalog=True, query='P04999', limit=50)
    assert result['total'] == 1 and result['nodes'][0]['product_ref'] == 'product:Product/P04999'
    assert ClientProductCatalogMixin.contract_tree_page(query='P04999')['total'] == 0
