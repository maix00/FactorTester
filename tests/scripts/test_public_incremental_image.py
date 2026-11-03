import os
from pathlib import Path
import subprocess

import pytest

from scripts.server import public_incremental_image as layer


@pytest.fixture
def repository(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    # These fixtures never inherit routing to a user's worktree or index.
    env={k:v for k,v in os.environ.items() if k not in {
        'GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY'}}
    def git(*args):
        return subprocess.run(['git','-C',str(root),*args],env=env,capture_output=True,check=True).stdout.decode().strip()
    git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
    def write(path,text):
        p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    write('server/service.py','original = 1\n');write('tools/cli/app.py','value = 1\n')
    write('deploy/requirements-public-linux.txt','fixed==1\n')
    git('add','.');git('commit','-qm','base');base=git('rev-parse','HEAD')
    return root,git,write,base


def commit(git):
    git('add','.');git('commit','-qm','candidate');return git('rev-parse','HEAD')


def test_app_only_delta_carries_exact_bytes_without_importing_source(repository):
    root,git,write,base=repository
    write('server/service.py',"raise RuntimeError('source must never execute during planning')\n")
    write('tools/cli/new_command.py','def command(): return 2\n')
    write('tests/unit.py','ignored = True\n');revision=commit(git)
    plan=layer.plan_changes(root,base,revision)
    assert {x['path'] for x in plan['files']}=={'server/service.py','tools/cli/new_command.py'}
    assert plan['tree']==git('rev-parse',revision+'^{tree}')
    assert plan['patch_bytes']==sum((root/x['path']).stat().st_size for x in plan['files'])
    assert next(x for x in plan['files'] if x['path']=='tools/cli/new_command.py')['old_sha256'] is None


@pytest.mark.parametrize('path',[
    'deploy/requirements-public-linux.txt','vendor/py-alpha-lib/source.py',
    'native/runtime.rs','deploy/docker/factortester-public/FactorTester.Dockerfile',
    'scripts/server/public_python_dependencies.py',
])
def test_dependency_native_and_build_input_changes_require_normal_build(repository,path):
    root,git,write,base=repository;write(path,'changed\n');revision=commit(git)
    with pytest.raises(ValueError,match='normal build'):
        layer.plan_changes(root,base,revision)


def test_dirty_or_wrong_candidate_and_oversized_delta_are_rejected(repository,monkeypatch):
    root,git,write,base=repository;write('server/service.py','next = 2\n');revision=commit(git)
    with pytest.raises(ValueError,match='exact clean'):
        layer.plan_changes(root,base,base)
    write('server/untracked.py','untracked = True\n')
    with pytest.raises(ValueError,match='exact clean'):
        layer.plan_changes(root,base,revision)
    (root/'server/untracked.py').unlink();monkeypatch.setattr(layer,'MAX_PATCH',1)
    with pytest.raises(ValueError,match='byte budget'):
        layer.plan_changes(root,base,revision)


def test_deleted_application_file_is_an_explicit_checked_operation(repository):
    root,git,write,base=repository;(root/'server/service.py').unlink();revision=commit(git)
    item=layer.plan_changes(root,base,revision)['files'][0]
    assert item['status']=='D' and item['old_sha256'] and item['new_sha256'] is None


def test_symlink_and_path_escape_cannot_enter_an_application_layer(repository):
    root,git,write,base=repository;(root/'server/link.py').symlink_to('../tools/cli/app.py');revision=commit(git)
    with pytest.raises(ValueError,match='links, submodules'):
        layer.plan_changes(root,base,revision)
    for path in ('../outside.py','/outside.py','server/../outside.py','server/.git/config','server//file.py'):
        with pytest.raises(ValueError):layer.valid_path(path)


def test_assembly_requires_explicit_authorization_before_docker_or_filesystem_writes(monkeypatch,tmp_path):
    monkeypatch.delenv('FACTORTESTER_PUBLISH_AUTHORIZED',raising=False)
    with pytest.raises(PermissionError,match='authorization'):
        layer.assemble(tmp_path,{},base_image='base',image='candidate',native_sha256='a'*64,work_root=tmp_path/'unused')
    assert not (tmp_path/'unused').exists()


def test_missing_resource_controls_and_host_headroom_cannot_be_ignored(tmp_path):
    info={key:True for key in ('MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit')};info['OSType']='linux'
    memory=tmp_path/'meminfo';memory.write_text('MemAvailable: 1048576 kB\nSwapFree: 999999999 kB\n')
    layer.require_resource_controls(info,meminfo=memory)
    for key in ('MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit'):
        with pytest.raises(ValueError,match='effective Linux resource controls'):
            layer.require_resource_controls({**info,key:False},meminfo=memory)
    memory.write_text('MemAvailable: 524288 kB\nSwapFree: 999999999 kB\n')
    with pytest.raises(ValueError,match='excluding swap'):
        layer.require_resource_controls(info,meminfo=memory)


def test_many_small_files_are_bounded_independently_of_content_bytes(repository,monkeypatch):
    root,git,write,base=repository
    write('server/a.py','');write('server/b.py','');revision=commit(git)
    monkeypatch.setattr(layer,'MAX_FILES',1)
    with pytest.raises(ValueError,match='too many files'):
        layer.plan_changes(root,base,revision)
    with pytest.raises(ValueError,match='Git output exceeds'):
        layer._git(root,'show',revision+':deploy/requirements-public-linux.txt',maximum_bytes=1)
