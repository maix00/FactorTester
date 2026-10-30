import json
import stat
import pytest
from scripts.migrations.keycloak_prepare_host import prepare


def test_prepare_creates_private_files_and_correct_identity_claims(tmp_path):
    root = tmp_path / 'identity'
    prepare(root, public_url='https://example.test:7998', network='manager-private', project='identity', realm='research')
    data = json.loads((root / 'import/realm.json').read_text())
    assert data['registrationAllowed'] is False
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / 'manager.env').stat().st_mode) == 0o600
    manager = next(c for c in data['clients'] if c['clientId'] == 'tr-manager')
    assert manager['directAccessGrantsEnabled'] is False
    claims = {m['name']: m['config']['user.attribute'] for m in manager['protocolMappers']}
    assert claims['tr_organization_id'] == 'organization_id'
    assert claims['tr_username'] == 'legacy_username'
    with pytest.raises(FileExistsError):
        prepare(root, public_url='https://example.test', network='manager-private', project='identity', realm='research')


@pytest.mark.parametrize('url,network,project', [
    ('https://example.test\n', 'private', 'identity'),
    ('https://example.test', 'private\nENV=value', 'identity'),
    ('https://example.test', 'private', 'x\nENV=value'),
    ('http://example.test', 'private', 'identity'),
])
def test_prepare_rejects_unsafe_environment_inputs_before_writing(tmp_path, url, network, project):
    root = tmp_path / 'identity'
    with pytest.raises(ValueError):
        prepare(root, public_url=url, network=network, project=project, realm='research')
    assert not root.exists()
