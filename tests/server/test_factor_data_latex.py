from __future__ import annotations

from flask import Flask

from server.modules.factors import data as factor_data
from server.modules.factors import factors_bp
from server.services import factor_registry


class _TemplateExpression:
    def to_latex(self):
        return r"\text{R}_{\textcolor{red}{N}}\text{ArgMaxRaw}(H_t)"


class _ResolvedExpression:
    def to_latex(self):
        return r"\text{R}_{25\,\mathrm{d}}\text{ArgMaxRaw}(H_t)"


class _Family:
    alias = "AroonMetadataFamily"
    params_dict = {}
    expr = _TemplateExpression()


class _Factor:
    alias = "AroonMetadataFamily|N:25d"
    name = alias
    family = _Family()
    freq = None
    _source_expr = _ResolvedExpression()


def test_factor_list_exposes_family_template_latex_not_resolved_default(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(factors_bp)
    monkeypatch.setattr(
        factor_data,
        "get_factor_family_instance",
        lambda *_args, **_kwargs: _Family(),
    )
    monkeypatch.setattr(
        factor_registry,
        "page_factors",
        {"page-1": {"factor": _Factor()}},
    )

    payload = app.test_client().get(
        "/api/factor_list?factor_family_alias=AroonMetadataFamily&page_uuid=page-1"
    ).get_json()

    assert payload["success"] is True
    assert payload["factors"][0]["latex"] == _TemplateExpression().to_latex()
    assert "25\\,\\mathrm{d}" not in payload["factors"][0]["latex"]
