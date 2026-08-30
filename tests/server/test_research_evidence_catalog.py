from __future__ import annotations

import settings as Settings
import pytest

from server.services.research_evidence_catalog import (
    attach_tag,
    create_evidence,
    create_tag,
    list_facets,
    list_source_fragments,
    list_tags,
    propose_tag,
    put_source_capture,
    put_source_fragment,
    search_evidence,
    finalize_lifecycle_transition,
    get_evidence_lifecycle,
    prepare_lifecycle_transition,
)
from tests.server.data_contract_fixtures import initialize
from tools.factors.formula_identity import freeze_factor_identity


def _source(owner: str = "alice") -> dict:
    return put_source_capture(
        owner=owner,
        source_kind="terminal",
        identity={"execution_id": "exec-1", "argv": ["python", "-V"]},
        content_hash="a" * 64,
        audit={"returncode": 0},
    )


def _fragment(
    source_ref: str,
    *,
    title: str = "版本输出",
    fragment_hash: str = "b" * 64,
) -> dict:
    return put_source_fragment(
        owner="alice",
        source_ref=source_ref,
        selector={"stream": "stdout", "line_range": {"start": 1, "end": 1}},
        fragment_hash=fragment_hash,
        title_zh=title,
        summary_zh="命令输出中的第一行版本信息",
        preview={"text": "Python 3.13"},
    )


def _evidence(fragment_ref: str, *, title: str = "运行环境版本") -> dict:
    return create_evidence(
        owner="alice",
        evidence_kind="data_availability",
        fragment_refs=[fragment_ref],
        title_zh=title,
        description_zh="确认当前真实命令运行环境的解释器版本",
        claim_summary="当前运行环境使用指定版本的解释器",
        applicability={
            "source_refs": ["environment:gtht"],
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        identity_refs={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        limitations=["只确认当前环境"],
        conflicts=[],
    )


def test_one_source_supports_multiple_fragments_and_evidence(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    source = _source()
    first = _fragment(source["source_ref"])
    second = put_source_fragment(
        owner="alice",
        source_ref=source["source_ref"],
        selector={"return_code": True},
        fragment_hash="e" * 64,
        title_zh="命令退出状态",
        summary_zh="命令以零状态正常结束",
        preview={"returncode": 0},
    )

    left = _evidence(first["fragment_ref"])
    right = _evidence(second["fragment_ref"], title="命令成功执行")

    assert left["evidence_ref"] != right["evidence_ref"]
    assert [item["fragment_ref"] for item in list_source_fragments(
        owner="alice", source_ref=source["source_ref"],
    )] == [first["fragment_ref"], second["fragment_ref"]]


def test_new_evidence_requires_an_owned_fragment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    try:
        _evidence("fragment:terminal:sha256:" + "f" * 64)
    except KeyError as exc:
        assert "fragment" in str(exc)
    else:
        raise AssertionError("missing fragment was accepted")


def test_content_refs_are_isolated_between_owners(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    alice_source = _source("alice")
    bob_source = _source("bob")

    assert alice_source["source_ref"] != bob_source["source_ref"]
    alice_fragment = _fragment(alice_source["source_ref"])
    bob_fragment = put_source_fragment(
        owner="bob",
        source_ref=bob_source["source_ref"],
        selector={"stream": "stdout", "line_range": {"start": 1, "end": 1}},
        fragment_hash="b" * 64,
        title_zh="版本输出",
        summary_zh="命令输出中的第一行版本信息",
        preview={"text": "Python 3.13"},
    )
    alice_evidence = _evidence(alice_fragment["fragment_ref"])
    bob_evidence = create_evidence(
        owner="bob",
        evidence_kind="data_availability",
        fragment_refs=[bob_fragment["fragment_ref"]],
        title_zh="运行环境版本",
        description_zh="确认当前真实命令运行环境的解释器版本",
        claim_summary="当前运行环境使用指定版本的解释器",
        applicability={
            "source_refs": ["environment:gtht"],
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        identity_refs={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        limitations=["只确认当前环境"],
        conflicts=[],
    )

    assert alice_fragment["fragment_ref"] != bob_fragment["fragment_ref"]
    assert alice_evidence["evidence_ref"] != bob_evidence["evidence_ref"]


def test_tags_are_mutable_facets_but_do_not_change_evidence_identity(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    evidence = _evidence(_fragment(_source()["source_ref"])["fragment_ref"])
    proposal = propose_tag(
        owner="alice",
        title_zh="运行环境",
        description_zh="用于检索解释器与运行时环境证据",
        created_by_profile_ref="profile:maxa",
    )
    assert proposal["proposal_token"]
    tag = create_tag(owner="alice", proposal_token=proposal["proposal_token"])
    attached = attach_tag(
        owner="alice",
        evidence_ref=evidence["evidence_ref"],
        tag_ref=tag["tag_ref"],
    )

    assert attached["evidence_ref"] == evidence["evidence_ref"]
    assert list_tags(owner="alice")[0]["evidence_count"] == 1
    facets = list_facets(owner="alice")
    assert "source_kind:terminal" in {
        item["facet_ref"] for item in facets["system"]
    }
    assert tag["tag_ref"] in {
        item["facet_ref"] for item in facets["agent"]
    }


def test_tag_proposal_blocks_near_duplicate_without_distinction_reason(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    proposal = propose_tag(
        owner="alice",
        title_zh="流动性证据",
        description_zh="用于定位成交量与可交易性证据",
        created_by_profile_ref="profile:maxa",
    )
    create_tag(owner="alice", proposal_token=proposal["proposal_token"])

    duplicate = propose_tag(
        owner="alice",
        title_zh="流动性证据集",
        description_zh="用于检索成交量和流动性证据",
        created_by_profile_ref="profile:maxa",
    )

    assert duplicate["proposal_token"] is None
    assert duplicate["candidates"]
    assert duplicate["next_actions"][0]["argv"][:3] == [
        "factortester", "research", "evidence",
    ]


def test_search_applies_scope_before_tags(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    source = _source()
    fragment = _fragment(source["source_ref"])
    factor = freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias="SgCCS",
        factor_alias="SgCCS",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
    )
    factor_ref = factor["ref"]
    evidence = create_evidence(
        owner="alice",
        evidence_kind="factor_semantics",
        fragment_refs=[fragment["fragment_ref"]],
        title_zh="工业硅因子语义",
        description_zh="确认指定工业硅因子版本的公式语义",
        claim_summary="该因子版本使用收盘价和期限结构输入",
        applicability={
            "product_refs": ["product:SI.GFE"],
            "factor_refs": [factor_ref],
            "factor_subjects": [factor],
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
            "time_window": {"start": "2025-01-01", "end": "2025-12-31"},
        },
        identity_refs={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        limitations=[],
        conflicts=[],
    )
    proposal = propose_tag(
        owner="alice",
        title_zh="工业硅",
        description_zh="工业硅产品相关研究证据",
        created_by_profile_ref="profile:maxa",
    )
    tag = create_tag(owner="alice", proposal_token=proposal["proposal_token"])
    attach_tag(
        owner="alice",
        evidence_ref=evidence["evidence_ref"],
        tag_ref=tag["tag_ref"],
    )

    matched = search_evidence(
        owner="alice",
        product_refs=["product:SI.GFE"],
        factor_refs=[factor_ref],
        time_window={"start": "2025-02-01", "end": "2025-03-01"},
        tag_refs=[tag["tag_ref"]],
    )
    rejected = search_evidence(
        owner="alice",
        product_refs=["product:AP.CZC"],
        tag_refs=[tag["tag_ref"]],
    )

    assert matched["items"][0]["evidence_ref"] == evidence["evidence_ref"]
    assert "product_ref" in matched["items"][0]["matched_by"]
    assert matched["next_actions"][0]["argv"][:3] == [
        "factortester", "research", "evidence",
    ]
    assert rejected["items"] == []


def test_excluded_evidence_is_hidden_until_a_reported_restore(
    monkeypatch, tmp_path,
) -> None:
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(path))
    initialize(path)
    evidence = _evidence(_fragment(_source()["source_ref"])["fragment_ref"])
    proposal = propose_tag(
        owner="alice",
        title_zh="待复核证据",
        description_zh="尚需确认适用范围的研究证据",
        created_by_profile_ref="profile:maxa",
    )
    tag = create_tag(
        owner="alice", proposal_token=proposal["proposal_token"],
    )
    attach_tag(
        owner="alice",
        evidence_ref=evidence["evidence_ref"],
        tag_ref=tag["tag_ref"],
    )
    prepared = prepare_lifecycle_transition(
        owner="alice",
        evidence_ref=evidence["evidence_ref"],
        action="exclude",
        reason_zh="该片段的时间范围与当前结论不一致",
        profile_ref="profile:maxa",
        agent_id="research-maxa",
        instance_id="instance-1",
        branch_id="branch-1",
        parent_id="node-data-contract",
    )

    assert search_evidence(owner="alice")["items"]
    finalized = finalize_lifecycle_transition(
        owner="alice",
        transition_ref=prepared["transition_ref"],
        report_receipt=_receipt("evidence-exclusion-one"),
    )

    assert finalized["status"] == "excluded"
    assert search_evidence(owner="alice")["items"] == []
    assert list_tags(owner="alice")[0]["evidence_count"] == 0
    with pytest.raises(ValueError, match="excluded Evidence"):
        attach_tag(
            owner="alice",
            evidence_ref=evidence["evidence_ref"],
            tag_ref=tag["tag_ref"],
        )
    audit = search_evidence(owner="alice", include_excluded=True)["items"]
    assert audit[0]["lifecycle_status"] == "excluded"
    assert get_evidence_lifecycle(
        owner="alice", evidence_ref=evidence["evidence_ref"],
    )["latest_transition"]["reason_zh"].startswith("该片段")

    restore = prepare_lifecycle_transition(
        owner="alice",
        evidence_ref=evidence["evidence_ref"],
        action="restore",
        reason_zh="补充核验后确认该片段可在限定范围内复用",
        profile_ref="profile:maxa",
        agent_id="research-maxa",
        instance_id="instance-1",
        branch_id="branch-1",
        parent_id="node-data-contract",
    )
    finalize_lifecycle_transition(
        owner="alice",
        transition_ref=restore["transition_ref"],
        report_receipt=_receipt("evidence-restore-one"),
    )
    assert search_evidence(owner="alice")["items"][0][
        "evidence_ref"
    ] == evidence["evidence_ref"]


def _receipt(component_id: str) -> dict:
    return {
        "submission_sequence": 1,
        "component_id": component_id,
        "git_commit": "a" * 40,
        "ledger_generation": 1,
        "ledger_projection_hash": "b" * 64,
    }
