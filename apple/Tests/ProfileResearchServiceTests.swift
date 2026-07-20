import XCTest
@testable import FTClient

final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(
        for request: URLRequest
    ) -> URLRequest { request }

    override func startLoading() {
        do {
            let (response, data) = try Self.handler!(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class ProfileResearchServiceTests: XCTestCase {
    func testProfileParsesFactorWorkspaceBinding() {
        let profile = LocalProfileModel(json: [
            "profile_id": "maxa",
            "factor_workspace_binding": [
                "binding_id": "factor-worktree-1",
                "branch": "agent/maxa",
                "worktree_path": "/profiles/maxa/factor-worktrees/maxa",
                "receipt_ref": "file:///receipt.json",
            ],
        ])

        XCTAssertEqual(profile.factorWorkspaceBinding?.id, "factor-worktree-1")
        XCTAssertEqual(profile.factorWorkspaceBinding?.branch, "agent/maxa")
    }

    func testLifecycleReceiptDefaultsToGitRetention() {
        let receipt = ProfileLifecycleReceipt(
            json: [
                "action": "delete",
                "status": "deleted",
                "profile_id": "maxa",
                "receipt_ref": "file:///receipt.json",
            ],
            fallbackAction: "unknown"
        )

        XCTAssertTrue(receipt.branchRetained)
        XCTAssertTrue(receipt.commitsRetained)
        XCTAssertEqual(receipt.profileID, "maxa")
    }

    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testConditionalRequestUsesETagAnd304DoesNotDecode() async throws {
        let session = stubSession()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "If-None-Match"),
                "\"detail-v1\""
            )
            return (
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 304,
                    httpVersion: nil,
                    headerFields: nil
                )!,
                Data()
            )
        }
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: URLSessionProfileResearchTransport(session: session)
        )
        let result = try await service.detail(
            href: "/api/profile-research/graph-branch:i:b",
            etag: "\"detail-v1\""
        )
        guard case .notModified = result else {
            return XCTFail("304 must not mutate or decode projection state")
        }
    }

    func testTimelineUsesBoundedKeysetQuery() async throws {
        let session = stubSession()
        StubURLProtocol.handler = { request in
            let components = URLComponents(
                url: request.url!,
                resolvingAgainstBaseURL: false
            )
            let values = Dictionary(
                uniqueKeysWithValues: components!.queryItems!.map {
                    ($0.name, $0.value ?? "")
                }
            )
            XCTAssertEqual(values["limit"], "50")
            XCTAssertEqual(values["after"], "opaque-cursor")
            let data = """
            {"success":true,"research_ref":"graph-branch:i:b",
             "items":[],"next_cursor":null,"etag":"sha256:page"}
            """.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["ETag": "\"page\""]
                )!,
                data
            )
        }
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: URLSessionProfileResearchTransport(session: session)
        )
        let result = try await service.timeline(
            href: "/api/profile-research/graph-branch:i:b/timeline",
            after: "opaque-cursor"
        )
        guard case .value(let page, _) = result else {
            return XCTFail("expected decoded page")
        }
        XCTAssertTrue(page.items.isEmpty)
        XCTAssertNil(page.nextCursor)
    }

    private func stubSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: configuration)
    }
}

private final class FakeClock: ResearchRefreshClock {
    private(set) var seconds: [Double] = []
    let cancelOnSleep: Bool
    init(cancelOnSleep: Bool) { self.cancelOnSleep = cancelOnSleep }
    func sleep(seconds: Double) async throws {
        self.seconds.append(seconds)
        if cancelOnSleep { throw CancellationError() }
    }
}

private final class SuspendingClock: ResearchRefreshClock {
    let started: XCTestExpectation
    init(started: XCTestExpectation) { self.started = started }
    func sleep(seconds: Double) async throws {
        started.fulfill()
        try await Task.sleep(nanoseconds: 60_000_000_000)
    }
}

private final class FakeProjectionTransport: ProfileResearchTransport {
    var responses: [ResearchHTTPResponse]
    var eventCount = 0
    private(set) var requests: [URLRequest] = []

    init(responses: [ResearchHTTPResponse]) {
        self.responses = responses
    }

    func data(for request: URLRequest) async throws -> ResearchHTTPResponse {
        requests.append(request)
        return responses.removeFirst()
    }

    func events(
        for request: URLRequest
    ) -> AsyncThrowingStream<Void, Error> {
        requests.append(request)
        return AsyncThrowingStream { continuation in
            eventCount += 1
            continuation.yield(())
            continuation.finish()
        }
    }
}

@MainActor
final class ProfileLiveProcessControllerTests: XCTestCase {
    func testTerminalDetailStopsWithoutClockOrSSE() async throws {
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh: #"{"mode":"stopped","terminal":true}"#
            )
        )
        let clock = FakeClock(cancelOnSleep: false)
        let controller = makeController(
            transport: transport,
            clock: clock
        )
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(controller.detail?.currentNode, "audit")
        XCTAssertEqual(controller.timeline.count, 1)
        XCTAssertTrue(clock.seconds.isEmpty)
        XCTAssertEqual(transport.eventCount, 0)
    }

    func testSSEEventRefreshesThenTerminalStops() async throws {
        let initial = fixtureResponses(
            detailRefresh:
                #"{"mode":"job_sse","href":"/api/jobs/j/stream","terminal":false}"#
        )
        let changedDetail = response(
            detailJSON(
                refresh: #"{"mode":"stopped","terminal":true}"#,
                node: "completed"
            ),
            etag: "\"detail-v2\""
        )
        let notModified = ResearchHTTPResponse(
            data: Data(), statusCode: 304, etag: "\"timeline-v1\""
        )
        let transport = FakeProjectionTransport(
            responses: initial + [changedDetail, notModified]
        )
        let controller = makeController(
            transport: transport,
            clock: FakeClock(cancelOnSleep: false)
        )
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(transport.eventCount, 1)
        XCTAssertEqual(controller.detail?.currentNode, "completed")
        XCTAssertEqual(controller.timeline.count, 1)
    }

    func testConditionalRefreshUsesMinimumFiveSecondsAndCancels() async {
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh:
                    #"{"mode":"conditional_etag","minimum_interval_seconds":1,"only_while_visible":true,"terminal":false}"#
            )
        )
        let clock = FakeClock(cancelOnSleep: true)
        let controller = makeController(
            transport: transport,
            clock: clock
        )
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(clock.seconds, [5])
        XCTAssertEqual(transport.requests.count, 3)
    }

    func testLeavingVisibleTaskCancelsRefreshWithoutMoreRequests() async {
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh:
                    #"{"mode":"conditional_etag","minimum_interval_seconds":5,"only_while_visible":true,"terminal":false}"#
            )
        )
        let started = expectation(description: "refresh sleep started")
        let profile = makeProfile()
        let controller = ProfileLiveProcessController(
            profile: profile,
            service: ProfileResearchService(
                baseURL: URL(string: "http://example.test")!,
                transport: transport
            ),
            clock: SuspendingClock(started: started)
        )
        await controller.loadSelectedWorkspace()
        let task = Task { await controller.observeSelectedResearch() }
        await fulfillment(of: [started], timeout: 1)
        task.cancel()
        await task.value
        XCTAssertEqual(transport.requests.count, 3)
    }

    private func makeController(
        transport: FakeProjectionTransport,
        clock: FakeClock
    ) -> ProfileLiveProcessController {
        let profile = makeProfile()
        return ProfileLiveProcessController(
            profile: profile,
            service: ProfileResearchService(
                baseURL: URL(string: "http://example.test")!,
                transport: transport
            ),
            clock: clock
        )
    }

    private func makeProfile() -> LocalProfileModel {
        LocalProfileModel(json: [
            "profile_id": "p",
            "display_name": "P",
            "server": ["base_url": "http://example.test"],
            "workspaces": [[
                "workspace_id": "w",
                "server_workspace_ref": "workspace:w",
            ]],
        ])
    }
}

private func fixtureResponses(
    detailRefresh: String
) -> [ResearchHTTPResponse] {
    [
        response(listJSON(), etag: "\"list-v1\""),
        response(detailJSON(refresh: detailRefresh), etag: "\"detail-v1\""),
        response(timelineJSON(), etag: "\"timeline-v1\""),
    ]
}

private func response(
    _ value: String,
    etag: String
) -> ResearchHTTPResponse {
    ResearchHTTPResponse(
        data: value.data(using: .utf8)!,
        statusCode: 200,
        etag: etag
    )
}

private func listJSON() -> String {
    """
    {"success":true,"workspace_ref":"workspace:w","items":[{
      "research_ref":"graph-branch:i:b","workspace_ref":"workspace:w",
      "label":"R","current_node":"audit","status":"running",
      "trial_plan_ref":"trial-plan:t","latest_trace_ref":"trace:s",
      "updated_at":1,"detail_href":"/api/profile-research/graph-branch:i:b",
      "report_lookup_ref":"graph-branch:i:b"}],
     "next_cursor":null,"etag":"sha256:list"}
    """
}

private func detailJSON(
    refresh: String,
    node: String = "audit"
) -> String {
    """
    {"success":true,"research_ref":"graph-branch:i:b","label":"R",
     "current_node":"\(node)","status":"running",
     "trial_plan_ref":"trial-plan:t",
     "report_lookup_ref":"graph-branch:i:b",
     "evidence_refs":["artifact:e"],"omitted_evidence_count":0,
     "research_cycle":{"claims":[],"obligations":[{
       "obligation_ref":"obligation:o","status":"open",
       "materiality":"blocking","question_summary":"costs?"}],"closure":null},
     "job_refs":["job:j"],"run_refs":["run:r"],
     "timeline_href":"/api/profile-research/graph-branch:i:b/timeline",
     "refresh":\(refresh),"etag":"sha256:detail"}
    """
}

private func timelineJSON() -> String {
    """
    {"success":true,"research_ref":"graph-branch:i:b","items":[{
      "step_ref":"trace:s","edge_ref":"graph-edge:e",
      "from_node":"trial","to_node":"audit","created_at":1,
      "evidence_refs":["artifact:e"],"trial_plan_refs":["trial-plan:t"],
      "obligation_refs":["obligation:o"],"claim_refs":[],
      "job_refs":["job:j"],"run_refs":["run:r"],
      "obligation_changes":[{"obligation_id":"o","from_state":"open",
      "to_state":"serviced"}],"claim_changes":[]}],
     "next_cursor":"older","etag":"sha256:timeline"}
    """
}
