"""登记必须幂等：相同参数的重复登记不得追加重复因子行。"""

from __future__ import annotations

from server.modules.custom_factors import factor_library_service as service


class _FakeFamily:
    def get_alias(self, **params):
        return "Fam|" + "|".join(f"{k}={v}" for k, v in sorted(params.items()))


def test_same_params_register_once(monkeypatch):
    params = {"Dur": "SgChgDurDay|P:[CA]|$F:30m", "$F": "30m"}
    store = {"rows": [], "factors": []}

    def load(u, f, scope):
        return {"params_list": [dict(r) for r in store["rows"]],
                "resolved_factors": list(store["factors"])}

    def save(username, family, rows, **kwargs):
        store["rows"] = [dict(r) for r in rows]
        store["factors"] = [{"ref": f"factor:v2:{i}", "alias": "Fam|"} for i in range(len(rows))]
        return {}, list(store["factors"])

    monkeypatch.setattr(service, "load_factor_param_config", load)
    monkeypatch.setattr(service, "get_account", lambda u: {"username": u})
    monkeypatch.setattr(service, "get_factor_family_instance", lambda f, username=None: _FakeFamily())
    monkeypatch.setattr(service, "save_current_user_library_config", save)

    first = service.save_single_library_factor("u", "Fam", dict(params))
    second = service.save_single_library_factor("u", "Fam", dict(params))
    assert len(store["rows"]) == 1, "相同参数的第二次登记不得追加新行"
    assert first[1]["ref"] == second[1]["ref"], "两次应返回同一记录"


def test_different_params_still_append(monkeypatch):
    store = {"rows": [{"N": "10d"}], "factors": [{"ref": "factor:v2:old", "alias": "Fam|N=10d"}]}

    def load(u, f, scope):
        return {"params_list": [dict(r) for r in store["rows"]],
                "resolved_factors": list(store["factors"])}

    def save(username, family, rows, **kwargs):
        store["rows"] = [dict(r) for r in rows]
        store["factors"] = [{"ref": f"factor:v2:{i}", "alias": "Fam|"} for i in range(len(rows))]
        return {}, list(store["factors"])

    monkeypatch.setattr(service, "load_factor_param_config", load)
    monkeypatch.setattr(service, "get_account", lambda u: {"username": u})
    monkeypatch.setattr(service, "get_factor_family_instance", lambda f, username=None: _FakeFamily())
    monkeypatch.setattr(service, "save_current_user_library_config", save)

    service.save_single_library_factor("u", "Fam", {"N": "20d"})
    assert len(store["rows"]) == 2, "不同参数应追加新行"
