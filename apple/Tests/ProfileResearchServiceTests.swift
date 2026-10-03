import Foundation
import XCTest
@testable import FTClient

final class ProfileResearchServiceTests: SimplifiedChineseLocalizedTestCase {
    func testEvidenceDetailDecodesAccessWithoutGraphContext() async throws {
        let transport = FakeProjectionTransport(responses: [response(
            """
            {"success":true,"evidence":{
              "evidence_ref":"evidence:v1:e1","evidence_kind":"job",
              "created_at":1,
              "envelope":{"schema_version":2,"envelope_id":"job:1",
                "envelope_hash":"abc","evidence_kind":"job",
                "title":"证据","claim_summary":"结论","facts":{},
                "source_refs":["job:1"],"metric_refs":[],
                "artifact_refs":[],"hypotheses_tested":0,
                "stop_condition":"","limitations":[],"conflicts":[]},
              "applicability":{},"fragments":[],"tags":[],
              "lifecycle":{"status":"active"}},
             "access":{"can_view":true,"can_preview":true,
               "can_download":false,"can_manage":false,
               "access_basis":"report"}}
            """,
            etag: "\"evidence-detail\""
        )])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!, transport: transport
        )

        let detail = try await service.evidenceDetail(reference: "evidence:v1:e1")

        XCTAssertEqual(detail.access?.accessBasis, "report")
        XCTAssertFalse(detail.access?.canDownload ?? true)
        XCTAssertEqual(transport.requests.first?.url?.path, "/api/research-evidence/evidence:v1:e1")
    }

    func testCanonicalResearchCatalogKeepsReportRelationships() async throws {
        let transport = FakeProjectionTransport(responses: [response(
            """
            {"success":true,"research":{
              "research_id":"research:v1:r1","owner_ref":"alice",
              "title":"动量研究","description":"","status":"active",
              "visibility":"authorized","authorized_users":[],
              "access":{"can_view":true,"can_preview":true,
                "can_download":true,"can_manage":false,
                "access_basis":"research"},
              "members":[{"research_id":"research:v1:r1",
                "principal_ref":"bob","profile_ref":"maxb",
                "role":"viewer","status":"active"}],
              "workspaces":[{"workspace_id":"workspace:v1:w1",
                "research_id":"research:v1:r1","principal_ref":"bob",
                "profile_ref":"maxb","title":"maxb workspace",
                "status":"active"}],
              "reports":[{"report_id":"report-1",
                "research_id":"research:v1:r1","owner_ref":"alice",
                "title":"结论","profile_ref":"maxb",
                "workspace_id":"workspace:v1:w1",
                "build_source":"server_agent","visibility":"public",
                "access":{"can_view":true,"can_preview":true,
                  "can_download":false,"can_manage":false,
                  "access_basis":"report"}}],
              "evidence_links":[]}}
            """,
            etag: "\"research-detail\""
        )])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!, transport: transport
        )

        let detail = try await service.research(researchID: "research:v1:r1")

        XCTAssertEqual(detail.members.first?.profileRef, "maxb")
        XCTAssertEqual(detail.workspaces.first?.researchID, detail.researchID)
        XCTAssertEqual(detail.reports.first?.access.accessBasis, "report")
        XCTAssertTrue(detail.access.canDownload)
        XCTAssertEqual(transport.requests.first?.url?.path, "/api/research/research:v1:r1")
    }

    func testResearchCreationUsesTheCanonicalResearchEndpoint() async throws {
        let transport = FakeProjectionTransport(responses: [response(
            """
            {"success":true,"research":{
              "research_id":"research:v1:new","owner_ref":"alice",
              "title":"新研究","description":"说明","status":"active",
              "visibility":"private","authorized_users":[],
              "access":{"can_view":true,"can_preview":true,
                "can_download":true,"can_manage":true,
                "access_basis":"owner"}}}
            """,
            etag: "\"research-create\""
        )])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!, transport: transport
        )

        let research = try await service.createResearch(
            title: "新研究", description: "说明"
        )

        XCTAssertEqual(research.researchID, "research:v1:new")
        XCTAssertEqual(transport.requests.first?.httpMethod, "POST")
        XCTAssertEqual(transport.requests.first?.url?.path, "/api/research")
    }

    func testDirectTrialPlanReferenceLoadsFromItsIndependentRegistry() async throws {
        let digest = String(repeating: "a", count: 64)
        let transport = FakeProjectionTransport(responses: [response(
            """
            {"success":true,"trial_plan":{
              "trial_plan_ref":"trial-plan:sha256:\(digest)",
              "trial_plan_hash":"\(digest)",
              "trial_plan":{"schema_version":1,"trial_plan_id":"plan-1",
                "comparisons":[{"comparison_id":"main"}]}}}
            """,
            etag: "\"trial-plan\""
        )])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!, transport: transport
        )

        let json = try await service.frozenObjectJSON(reference: .init(
            kind: "trial_plan",
            targetRef: "trial-plan:sha256:\(digest)",
            label: "试验计划"
        ))

        XCTAssertEqual(transport.requests.first?.url?.path, "/api/trial-plans/direct/\(digest)")
        let value = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
        )
        XCTAssertEqual(value["trial_plan_id"] as? String, "plan-1")
        XCTAssertNil(value["trial_plan_hash"])
    }

    func testManagerRoutedResearchEventKeepsUnifiedOriginAndAuth() async throws {
        let transport = FakeProjectionTransport(responses: [])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://127.0.0.1:7998")!,
            transport: transport,
            servicePort: 8141,
            managerToken: "manager-user-token"
        )

        for try await _ in service.events(href: "/api/jobs/one/events") {}

        let request = try XCTUnwrap(transport.eventRequests.first)
        XCTAssertEqual(request.url?.port, 7998)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer manager-user-token")
        XCTAssertTrue(request.url?.query?.contains("port=8141") == true)
    }
}

private final class FakeProjectionTransport: ProfileResearchTransport {
    var responses: [ResearchHTTPResponse]
    private(set) var requests: [URLRequest] = []
    private(set) var eventRequests: [URLRequest] = []

    init(responses: [ResearchHTTPResponse]) {
        self.responses = responses
    }

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        requests.append(request)
        return responses.removeFirst()
    }

    func events(for request: URLRequest) -> AsyncThrowingStream<Void, Error> {
        eventRequests.append(request)
        return AsyncThrowingStream { continuation in continuation.finish() }
    }
}

private func response(_ value: String, etag: String?) -> ResearchHTTPResponse {
    ResearchHTTPResponse(
        data: Data(value.utf8), statusCode: 200, etag: etag
    )
}
