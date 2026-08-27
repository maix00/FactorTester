from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.modules import agents as agent_commands
from tools.cli.modules import research as research_commands
from tools.cli.modules.products import catalog as product_catalog_commands
from tools.cli.modules.products import controller as product_controller_commands
from tools.cli.modules.products import data_sources as product_source_commands


def test_root_exposes_business_domains_without_split_legacy_groups() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0, result.output
    assert "products" in result.output
    assert "research" in result.output
    assert "agents" in result.output
    assert "profile-agent" not in result.output
    assert "agent-flow" not in result.output
    assert "research-graph" not in result.output
    assert "research-evidence" not in result.output


def test_products_list_reads_the_real_server_catalog(monkeypatch) -> None:
    class Client:
        def product_catalog(self):
            return {"products": [{"name": "RB.SHF", "description": "螺纹钢"}]}

    monkeypatch.setattr(
        product_catalog_commands, "client_from_config", lambda: Client(),
    )
    result = CliRunner().invoke(cli, ["products", "list", "--json"])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["object_type"] == "product"
    assert value["items"][0]["name"] == "RB.SHF"


def test_products_sources_share_the_server_catalog(monkeypatch) -> None:
    class Client:
        def product_source_catalog(self):
            return {"sources": [{"name": "LocalCNFutures", "frequency": "MIN1"}]}

    monkeypatch.setattr(
        product_source_commands, "client_from_config", lambda: Client(),
    )
    result = CliRunner().invoke(cli, ["products", "sources", "list", "--json"])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["object_type"] == "data_source"
    assert value["items"][0]["name"] == "LocalCNFutures"


def test_products_groups_share_the_web_manager_catalog(monkeypatch) -> None:
    class Client:
        def product_group_catalog(self):
            return {"groups": [{
                "group_ref": "product-group:group-1",
                "name": "我的产品组",
            }]}

    monkeypatch.setattr(
        product_controller_commands, "client_from_config", lambda: Client(),
    )
    result = CliRunner().invoke(cli, ["products", "groups", "list", "--json"])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["groups"][0]["group_ref"] == "product-group:group-1"


def test_research_reports_use_web_scope_semantics(monkeypatch) -> None:
    class Client:
        def research_report_catalog(self, *, scope):
            assert scope == "subordinates"
            return {"reports": [{"title": "下级研究", "build_source": "server_agent"}]}

    monkeypatch.setattr(
        research_commands, "client_from_config", lambda: Client(),
    )
    result = CliRunner().invoke(cli, [
        "research", "reports", "list", "--scope", "subordinates", "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["scope"] == "subordinates"
    assert value["items"][0]["build_source"] == "server_agent"


def test_research_profiles_use_the_web_directory(monkeypatch) -> None:
    class Client:
        def profile_directory(self, *, scope, query, page, page_size):
            assert (scope, query, page, page_size) == ("mine", "alpha", 1, 20)
            return {"items": [{
                "profile_id": "alpha",
                "runtime": {"runtime_kind": "server"},
            }]}

    monkeypatch.setattr(
        research_commands, "client_from_config", lambda: Client(),
    )
    result = CliRunner().invoke(cli, [
        "research", "profiles", "list", "--scope", "mine", "--query", "alpha", "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["profile_id"] == "alpha"


def test_agents_models_use_the_manager_provider_catalog(monkeypatch) -> None:
    class Client:
        def list_agent_models(self, *, runtime_kind=None):
            assert runtime_kind == "server"
            return [{
                "provider_id": "codex",
                "display_name": "Codex",
                "runtime_kind": "server",
            }]

    monkeypatch.setattr(agent_commands, "client_from_config", lambda: Client())
    result = CliRunner().invoke(cli, [
        "agents", "models", "list", "--runtime-kind", "server", "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["provider_id"] == "codex"


def test_nested_domain_help_matches_web_modules() -> None:
    runner = CliRunner()
    products = runner.invoke(cli, ["products", "--help"])
    research = runner.invoke(cli, ["research", "--help"])
    agents = runner.invoke(cli, ["agents", "--help"])

    assert products.exit_code == research.exit_code == agents.exit_code == 0
    for command in ("list", "groups", "categories", "sources"):
        assert command in products.output
    for command in ("reports", "graphs", "evidence", "profiles", "workspaces"):
        assert command in research.output
    for command in ("models", "profile", "flow"):
        assert command in agents.output
