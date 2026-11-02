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
