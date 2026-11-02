from types import SimpleNamespace
import pytest
from server.modules.shared.param_meta import serialize_param_meta

@pytest.mark.parametrize('alias',['N','$F','$Rev'])
def test_parameter_label_uses_public_alias_not_runtime_object_name(alias):
    row=serialize_param_meta(SimpleNamespace(alias=alias,name=alias+':'+'a'*32,default_value=None))
    assert row['alias']==alias
    assert row['name']==alias
