import XCTest
@testable import FTClient

final class ResearchDocumentReferenceDetailsTests: SimplifiedChineseLocalizedTestCase {
    func testFactorSetListsEveryMemberAsAnInternalFactorLink() throws {
        let raw: [String: Any] = [
            "binding_id": "binding-set",
            "component_id": "component-set",
            "kind": "factor",
            "target_ref": "factor-set:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "label": "动量因子集合",
            "data": [
                "object_kind": "factor-set",
                "set_id": "momentum-2025",
                "member_refs": [
                    "factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "factor:v2:ccccccccccccccccccccccccccccccccccccccccccc"
                ],
                "related_references": [[
                    "relation": "集合成员",
                    "kind": "factor",
                    "target_ref": "factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "label": "TrMomentum|N:20d",
                    "data": ["identity": "TrMomentum|N:20d"],
                ], [
                    "relation": "集合成员",
                    "kind": "factor",
                    "target_ref": "factor:v2:ccccccccccccccccccccccccccccccccccccccccccc",
                    "label": "MmTrend|N:20d",
                    "data": ["identity": "MmTrend|N:20d"],
                ]],
            ],
        ]
        let binding = try XCTUnwrap(
            ResearchDocumentParser.parseBinding(raw)
        )
        let reference = ResearchDocumentTypedLink(
            kind: "factor",
            targetRef: "factor-set:v2:" + String(repeating: "a", count: 43),
            label: "动量因子集合",
            componentID: "component-set"
        )

        let sections = ResearchDocumentReferenceDetails.sections(
            reference: reference,
            binding: binding,
            payload: nil,
            evidence: nil
        )

        XCTAssertEqual(sections[0].links.map(\.reference.label), [
            "TrMomentum|N:20d", "MmTrend|N:20d",
        ])
        XCTAssertNil(value("member refs", in: sections))
        XCTAssertEqual(
            ResearchDocumentReferenceBindingResolver.binding(
                for: sections[0].links[0].reference,
                in: [binding]
            )?.detailFields.first?.value,
            "TrMomentum|N:20d"
        )
    }

    func testEvidenceExplainsClaimFactsAndApplicability() throws {
        let detail = try decode(ResearchEvidenceDetailPayload.self, """
        {"evidence_ref":"evidence:authoritative_backtest:sha256:abc",
         "evidence_kind":"authoritative_backtest","created_at":1,
         "envelope":{"schema_version":2,"envelope_id":"backtest:1",
           "envelope_hash":"abc","evidence_kind":"authoritative_backtest",
           "title":"手续费后回测","claim_summary":"净收益仍为正",
           "facts":{"net_return_positive":true},
           "source_refs":["job:1"],"metric_refs":["net_return"],
           "artifact_refs":["artifact:equity"],"hypotheses_tested":1,
           "stop_condition":"预注册窗口结束","limitations":["仅适用于当前样本"],
           "conflicts":[]},
         "applicability":{"product_refs":["RB.SHF"],
           "time_window":{"start":"2025-01-01","end":"2025-12-31"}}}
        """)
        let sections = ResearchDocumentReferenceDetails.sections(
            reference: .init(
                kind: "evidence",
                targetRef: detail.evidenceRef,
                label: "手续费后回测"
            ),
            binding: nil,
            payload: nil,
            evidence: detail
        )

        XCTAssertEqual(value("证明内容", in: sections), "净收益仍为正")
        XCTAssertEqual(value("事实 · net return positive", in: sections), "是")
        XCTAssertEqual(value("产品", in: sections), "RB.SHF")
        XCTAssertEqual(value("时间范围 · 开始", in: sections), "2025-01-01")
        XCTAssertEqual(detail.lifecycle.status, "active")
    }

    func testEvidenceShowsFrozenFactorAsRelatedFactorLink() throws {
        let target = "factor:v2:" + String(repeating: "a", count: 43)
        let familyRef = "factor-family:v2:" + String(
            repeating: "b", count: 43
        )
        let detail = try decode(ResearchEvidenceDetailPayload.self, """
        {"evidence_ref":"evidence:factor_semantics:sha256:abc",
         "evidence_kind":"factor_semantics","created_at":1,
         "envelope":{"schema_version":3,"evidence_kind":"factor_semantics",
           "title":"端点动量语义","claim_summary":"端点收益定义"},
         "applicability":{"factor_refs":["\(target)"],
           "factor_subjects":[{"schema_version":2,"ref":"\(target)",
             "alias":"MmRateOfChg|P:[CA]|N:20d|$F:1d",
             "owner_ref":"profile:maxa","identity":{
               "family_ref":"\(familyRef)","family_alias":"MmRateOfChg",
               "family_formula_fingerprint":"\(String(repeating: "c", count: 64))",
               "self_formula_fingerprint":"\(String(repeating: "d", count: 64))",
               "params":{"P":["CA"],"N":"20d","$F":"1d"}}}]}}
        """)
        let sections = ResearchDocumentReferenceDetails.sections(
            reference: .init(
                kind: "evidence",
                targetRef: detail.evidenceRef,
                label: "端点动量语义"
            ),
            binding: nil,
            payload: nil,
            evidence: detail
        )

        let links = sections.flatMap(\.links)
        XCTAssertEqual(links.map(\.reference.kind), ["factor"])
        XCTAssertEqual(links.map(\.reference.targetRef), [target])
        XCTAssertEqual(
            links.map(\.reference.label),
            ["MmRateOfChg|P:[CA]|N:20d|$F:1d"]
        )
        XCTAssertNil(value("因子", in: sections))
    }

    func testExcludedEvidenceRemainsReadableAndShowsRuling() throws {
        let detail = try decode(ResearchEvidenceDetailPayload.self, """
        {"evidence_ref":"evidence:diagnostic:sha256:abc",
         "evidence_kind":"diagnostic","created_at":1,
         "envelope":{"schema_version":3,"evidence_kind":"diagnostic",
           "title":"过期诊断","claim_summary":"旧环境中的诊断结论"},
         "applicability":{},
         "lifecycle":{"status":"excluded","latest_transition":{
           "action":"exclude","reason_zh":"该证据不适用于冻结环境",
           "updated_at":2}}}
        """)
        let sections = ResearchDocumentReferenceDetails.sections(
            reference: .init(
                kind: "evidence",
                targetRef: detail.evidenceRef,
                label: "过期诊断"
            ),
            binding: nil,
            payload: nil,
            evidence: detail
        )

        XCTAssertEqual(detail.lifecycle.status, "excluded")
        XCTAssertEqual(value("证据状态", in: sections), L10n.text("已排除"))
        XCTAssertEqual(
            value("生命周期理由", in: sections),
            "该证据不适用于冻结环境"
        )
    }

    func testFrozenTrialPlanUsesCompleteJSONReturnedByCycleObject() throws {
        let payload = try decode(ResearchAuditObjectPayload.self, """
        {"schema_version":1,"trial_plan_id":"plan-1",
         "complete_parameters_json":"{\\n  \\"trial_plan_id\\": \\"plan-1\\"\\n}"}
        """)

        XCTAssertEqual(
            ResearchFrozenObjectJSON.resolve(
                kind: "trial_plan",
                payload: payload,
                registryJSON: nil
            ),
            "{\n  \"trial_plan_id\": \"plan-1\"\n}"
        )
    }

    func testDirectRunSpecUsesLazilyLoadedRegistryJSON() {
        XCTAssertEqual(
            ResearchFrozenObjectJSON.resolve(
                kind: "run_spec",
                payload: nil,
                registryJSON: "{\"run_spec_version\":2}"
            ),
            "{\"run_spec_version\":2}"
        )
    }

    func testEvidenceFallbackUsesPersistentRegistryEndpoint() async throws {
        let transport = ReferenceDetailTransport()
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )
        _ = try await service.evidence(
            reference: "evidence:factor_semantics:sha256:abc"
        )

        XCTAssertEqual(
            transport.request?.url?.path,
            "/api/research-evidence/evidence:factor_semantics:sha256:abc"
        )
    }

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    private func value(
        _ name: String,
        in sections: [ResearchDocumentReferenceSection]
    ) -> String? {
        sections.flatMap(\.fields).first { $0.name == name }?.value
    }
}

private final class ReferenceDetailTransport: ProfileResearchTransport {
    var request: URLRequest?

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        self.request = request
        return ResearchHTTPResponse(
            data: Data("""
            {"success":true,"evidence":{"evidence_ref":"evidence:factor_semantics:sha256:abc","evidence_kind":"factor_semantics","created_at":1,"envelope":{"schema_version":2,"evidence_kind":"factor_semantics"},"applicability":{"factor_refs":["factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}}}
            """.utf8),
            statusCode: 200,
            etag: nil
        )
    }

    func events(for request: URLRequest) -> AsyncThrowingStream<Void, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}
