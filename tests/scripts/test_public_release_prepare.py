"""Execute the preparation phase with isolated files and fake host commands."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def executable(path, body):
    path.write_text('#!/bin/bash\nset -e\n' + body)
    path.chmod(0o700)


def test_prepare_builds_new_image_without_touching_application_or_database(tmp_path):
    revision, old, native = 'a'*40, 'b'*40, 'c'*64
    git_root, container = tmp_path/'git', tmp_path/'container'
    (git_root/'repo.git').mkdir(parents=True)
    release = container/'releases'/revision
    scripts = release/'scripts/server'; scripts.mkdir(parents=True)
    (release/'.git').touch()
    artifact = container/'native-wheels'/native; artifact.mkdir(parents=True)
    (artifact/'build-id.txt').write_text(native)
    (artifact/'payload').write_bytes(b'cached native artifact')
    (artifact/'checksums.sha256').write_text(hashlib.sha256(b'cached native artifact').hexdigest()+'  payload\n')
    environment = tmp_path/'public.env'
    environment.write_text('FACTORTESTER_REVISION='+old+'\n')
    commands = tmp_path/'bin'; commands.mkdir()
    executable(commands/'sudo', 'exec "$@"\n')
    executable(commands/'flock', 'exit 0\n')
    executable(commands/'git', f'case "$*" in *rev-parse*) echo {revision};; esac\n')
    executable(commands/'docker', f'echo factortester-public:{old}\n')
    executable(commands/'sha256sum', 'exec /usr/bin/shasum -a 256 "$@"\n')
    # The production script runs GNU sed; use the macOS spelling in this test.
    executable(commands/'sed', '''if [[ "$1" == "-i" && "$(uname)" == Darwin ]]; then
shift; exec /usr/bin/sed -i '' "$@"
fi
exec /usr/bin/sed "$@"
''')
    log = tmp_path/'calls'
    executable(scripts/'factortester_public_container.sh', '''echo "$*" >> "$TR_TEST_CALLS"
case "$1" in
container-id) echo current-application;;
python-cache-plan) echo '{"snapshot_mib":1}';;
build) :;;
*) echo 'unexpected activation or database operation' >&2; exit 88;;
esac
''')
    executable(scripts/'check_public_build_capacity.sh', 'exit 0\n')
    env = dict(os.environ, PATH=str(commands)+os.pathsep+os.environ['PATH'], TR_TEST_CALLS=str(log))
    result = subprocess.run(['bash', str(ROOT/'scripts/server/activate_public_revision.sh'), revision,
        str(git_root), str(container), str(environment), '3', native, '1'], env=env,
        capture_output=True, text=True, check=True)
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt == dict(status='prepared', revision=revision, native_build_id=native,
                           application_activated=False)
    assert environment.read_text() == 'FACTORTESTER_REVISION='+old+'\n'
    assert log.read_text().splitlines() == ['container-id factortester-public', 'python-cache-plan', 'build factortester-public']
    assert (git_root/'deployments.log').read_text() == ''
    assert not Path(str(environment)+'.before-'+revision).exists()
    assert 'FACTORTESTER_REVISION='+revision in Path(str(environment)+'.next-'+revision).read_text()


def test_invalid_preparation_mode_fails_before_host_or_git_operations(tmp_path):
    result = subprocess.run(['bash', str(ROOT/'scripts/server/activate_public_revision.sh'),
        'a'*40, str(tmp_path/'git'), str(tmp_path/'container'), str(tmp_path/'public.env'), '3', 'c'*64, 'yes'],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert 'prepare-only must be 0 or 1' in result.stderr
    assert list(tmp_path.iterdir()) == []
