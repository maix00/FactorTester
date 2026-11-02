from types import SimpleNamespace
import json
import pytest
from scripts.server.public_prebuilt_image import inspect_prepared


def test_only_exact_release_inputs_reuse_image():
 labels={'org.opencontainers.image.revision':'release','org.traderesearch.nautilus.revision':'native','org.traderesearch.python-deps.identity':'deps'}
 def run(args,**kwargs):return SimpleNamespace(returncode=0,stdout=json.dumps([{'Id':'sha256:'+'a'*64,'Config':{'Labels':labels}}]))
 assert inspect_prepared('candidate',revision='release',nautilus_revision='native',python_deps_id='deps',run=run)=='sha256:'+'a'*64
 for key in labels:
  old=labels[key];labels[key]='other'
  with pytest.raises(ValueError,match='frozen release inputs'):
   inspect_prepared('candidate',revision='release',nautilus_revision='native',python_deps_id='deps',run=run)
  labels[key]=old


def test_missing_image_is_distinct_from_daemon_failure():
 def run(args,**kwargs):return SimpleNamespace(returncode=1,stderr='Error: No such image: candidate')
 assert inspect_prepared('candidate',revision='x',nautilus_revision='y',python_deps_id='z',run=run) is None
 def failure(args,**kwargs):return SimpleNamespace(returncode=1,stderr='Cannot connect to Docker daemon')
 with pytest.raises(RuntimeError,match='cannot inspect'):
  inspect_prepared('candidate',revision='x',nautilus_revision='y',python_deps_id='z',run=failure)
