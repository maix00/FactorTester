import XCTest
@testable import FTClient

final class ResearchDocumentReferenceDetailsTests: XCTestCase {
    func testObligationExplainsQuestionScopeAndCompletionCriterion() throws {
        let payload = try decode(ResearchAuditObjectPayload.self, """
        {"schema_version":1,"obligation_id":"fees","obligation_kind":"cost_test",
         "epistemic_question":"手续费后收益能否保持为正？",
         "scope":{"product_group":"CNFutures"},
         "discharge_criterion":{"rule_ref":"net-return:positive"},
         "requirement_refs":["requirement:fees"],"claim_ids":["claim:alpha"],
         "status":"open","materiality":"decision_blocking",
         "created_event_ref":"trace:start"}
        """)
        let sections = ResearchDocumentReferenceDetails.sections(
            reference: .init(
                kind: "obligation",
                targetRef: "obligation:fees",
                label: "手续费覆盖义务"
            ),
            binding: nil,
            payload: payload,
            evidence: nil
        )

        XCTAssertEqual(value("待回答问题", in: sections), "手续费后收益能否保持为正？")
        XCTAssertEqual(value("完成标准 · 规则", in: sections), "net-return:positive")
        XCTAssertEqual(value("范围 · 产品组", in: sections), "CNFutures")
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
            {"success":true,"evidence":{"evidence_ref":"evidence:factor_semantics:sha256:abc","evidence_kind":"factor_semantics","created_at":1,"envelope":{"schema_version":2,"evidence_kind":"factor_semantics"},"applicability":{"factor_refs":["factor:1"]}}}
            """.utf8),
            statusCode: 200,
            etag: nil
        )
    }

    func events(for request: URLRequest) -> AsyncThrowingStream<Void, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}
