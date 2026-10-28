from pathlib import Path
import scripts.migrations.purge_legacy_authority_paths as mod


def test_purge_module_imports():
    assert callable(mod.main)
