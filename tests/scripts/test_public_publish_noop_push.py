"""Exercise the actual publication push block without network/build operations."""
from pathlib import Path
import os,subprocess
import pytest

@pytest.mark.parametrize('already_published',[True,False])
def test_published_main_does_not_retrigger_push_hooks(tmp_path,already_published):
    root=Path(__file__).resolve().parents[2]
    source=(root/'scripts/server/publish_public_main.sh').read_text()
    block=source.split('if [[ "$skip_github" == "1" ]]; then\n  echo "Skipping GitHub push',1)[1]
    block='if [[ "$skip_github" == "1" ]]; then\n  echo "Skipping GitHub push'+block.split('\nremote_exec "command -v git',1)[0]
    harness='''set -eu
repo_root=/reviewed-main; revision=abc; skip_github=0
calls="$1"
git() { if [[ "$3" == rev-parse ]]; then printf '%s\\n' "$REMOTE_REF"; else printf 'push\\n' >> "$calls"; fi; }
'''+block
    calls=tmp_path/'calls'
    env={**os.environ,'REMOTE_REF':'abc' if already_published else 'older'}
    subprocess.run(['bash','-c',harness,'publish-test',str(calls)],env=env,check=True,capture_output=True,text=True)
    assert calls.exists() is (not already_published)
    if calls.exists():assert calls.read_text()=='push\n'


@pytest.mark.parametrize('choice,expected', [(None,False), ('0',False), ('1',True)])
def test_release_cleanup_runs_only_for_explicit_choice(tmp_path, choice, expected):
    root=Path(__file__).resolve().parents[2]
    source=(root/'scripts/server/activate_public_revision.sh').read_text()
    block=source.split('# Removing retained release worktrees/images requires explicit cleanup scope.',1)[1]
    calls=tmp_path/'cleanup-calls'
    assignment=next(line for line in source.splitlines() if line.startswith('cleanup_releases='))
    harness='set -eu\n'+assignment+'''
revision=test;release_retention=3
cleanup_old_application_releases() { printf 'release-cleanup\\n' >> "$CALLS"; }
sudo() { echo 'unexpected global Docker operation' >&2; exit 99; }
'''+block
    env={**os.environ,'CALLS':str(calls)}
    args=['bash','-c',harness,'cleanup-test',*(['placeholder']*7)]
    if choice is not None:args.append(choice)
    subprocess.run(args,env=env,check=True,capture_output=True,text=True)
    assert calls.exists() is expected


def test_invalid_cleanup_choice_is_rejected_before_git_or_transfer(tmp_path):
    root=Path(__file__).resolve().parents[2]
    bindir=tmp_path/'bin';bindir.mkdir()
    calls=tmp_path/'calls'
    for name in ['git','ssh']:
        executable=bindir/name
        executable.write_text('#!/bin/sh\necho called >> "$CALLS"\nexit 99\n')
        executable.chmod(0o755)
    env={**os.environ,'PATH':str(bindir)+os.pathsep+os.environ['PATH'],
         'FACTORTESTER_PUBLISH_AUTHORIZED':'1','FACTORTESTER_CLEANUP_RELEASES':'invalid',
         'CALLS':str(calls)}
    result=subprocess.run(['bash',str(root/'scripts/server/publish_public_main.sh')],
                          env=env,capture_output=True,text=True)
    assert result.returncode==2
    assert 'FACTORTESTER_CLEANUP_RELEASES must be 0 or 1' in result.stderr
    assert not calls.exists()
