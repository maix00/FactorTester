from pathlib import Path
import pytest
from server.jobs.dispatch.remote import validate_node_runtime_revision


def test_image_cannot_register_another_deployment(tmp_path):
    revision='a'*40
    (tmp_path/'.deployment-revision').write_text(revision+'\n')
    validate_node_runtime_revision({'target':{'deployment_ref':revision}},root=tmp_path)
    for other in ('b'*40,'old-deployment',''):
        with pytest.raises(ValueError,match='actual image revision'):
            validate_node_runtime_revision({'target':{'deployment_ref':other}},root=tmp_path)


def test_editable_install_has_no_fabricated_image_identity(tmp_path):
    descriptor={'target':{'deployment_ref':'installer-selected'}}
    validate_node_runtime_revision(descriptor,root=tmp_path)
    assert descriptor['target']['deployment_ref']=='installer-selected'
    (tmp_path/'.deployment-revision').write_text('bad')
    with pytest.raises(ValueError,match='receipt is invalid'):
        validate_node_runtime_revision(descriptor,root=tmp_path)
