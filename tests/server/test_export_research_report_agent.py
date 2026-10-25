from pathlib import Path
import scripts.migrations.export_research_report_agent as mod


def test_export_script_imports():
    assert callable(mod.main)
