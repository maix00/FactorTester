import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('native_upload', Path(__file__).parents[2] / 'scripts/server/upload_native_context.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_upload_preserves_bytes_with_bounded_chunks_and_removes_chunks(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    target = tmp_path / 'target with spaces'; target.mkdir()
    (source / 'runtime.whl').write_bytes(bytes(range(255)) * 5)
    (source / 'build-id.txt').write_text('identity')
    module.upload_context(source, str(target), ['sh', '-c'], workers=2, chunk_bytes=61)
    assert sorted(p.name for p in source.iterdir()) == sorted(p.name for p in target.iterdir())
    for path in source.iterdir():
        assert path.read_bytes() == (target / path.name).read_bytes()


def test_upload_rejects_source_trees_and_unbounded_workers(tmp_path):
    (tmp_path / 'secret.env').write_text('not-an-artifact')
    with pytest.raises(ValueError):
        module.upload_context(tmp_path, '/unused', ['false'])
    with pytest.raises(ValueError):
        module.upload_context(tmp_path, '/unused', ['false'], workers=100)
