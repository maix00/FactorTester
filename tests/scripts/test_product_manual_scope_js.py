from pathlib import Path
import subprocess


def test_manual_product_scope_uses_shared_constraints_and_complete_pages():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", "tests/js/test_test_products_manual_scope.js"], cwd=root, check=True)
