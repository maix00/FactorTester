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
    func testResearchTreeLanesStayInsideFixedNavigatorWidth() {
        XCTAssertLessThanOrEqual(
            ResearchTreeLayout.maximumLaneFootprint,
            ResearchTreeLayout.navigatorWidth
                - ResearchTreeLayout.horizontalPadding * 2
        )
        XCTAssertEqual(ResearchTreeLayout.maximumVisibleBranches, 7)
    }

    func testTimelineResolvesCycleObjectAtItsOwnCheckpoint() throws {
        let page = try JSONDecoder().decode(
            ProfileResearchTimelinePage.self,
            from: timelineJSON().data(using: .utf8)!
        )
        let step = try XCTUnwrap(page.items.first)

        XCTAssertEqual(
            step.objectHref(
                kind: "obligation",
                targetRef: "obligation:o"
            ),
            "/api/research-graph-instances/i/branches/b/"
                + "cycle-objects/obligation/o?trace_id=s"
        )
    }

    func testAuditObjectLoadsOnlyWhenExplicitHrefIsRequested() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
                """
                {"success":true,"object":{
                  "schema_version":1,"obligation_id":"o",
                  "obligation_kind":"semantic_test",
                  "epistemic_question":"Does the mechanism survive?",
                  "scope":{"product_group":"CNFutures"},
                  "discharge_criterion":{"rule_ref":"semantic:survival"},
                  "status":"open","materiality":"decision_blocking",
                  "created_event_ref":"trace:init"}}
                """,
                etag: "\"object-v1\""
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let object = try await service.auditObject(
            href: "/api/research-graph-instances/i/branches/b/"
                + "cycle-objects/obligation/o?trace_id=s"
        )

        XCTAssertEqual(object.obligationID, "o")
        XCTAssertEqual(
            object.epistemicQuestion,
            "Does the mechanism survive?"
        )
        XCTAssertEqual(transport.requests.count, 1)
        XCTAssertEqual(transport.requests[0].url?.query, "trace_id=s")
    }

    func testWorkPackageDecodesAuthoritativeBranchLineage() throws {
        let detail = try JSONDecoder().decode(
            ProfileResearchWorkPackageDetail.self,
            from: workPackageJSON().data(using: .utf8)!
        )
        let lineage = try XCTUnwrap(detail.branches.first?.lineage)

        XCTAssertEqual(lineage.relation, "fork")
        XCTAssertEqual(
            lineage.sourceBranchRef,
            "graph-branch:i:parent"
        )
        XCTAssertEqual(lineage.sourceTraceRef, "trace:parent-step")
        XCTAssertNil(lineage.sourceCheckpointHash)
        XCTAssertEqual(detail.branches.first?.createdAt, 1)
    }

    @MainActor
    func testResearchDirectoryAssignsSharedWorkspaceResearchToExactProfile() async {
        let profiles = [
            ("maxa", "http://EXAMPLE.test:8141/", "i", "b"),
            ("maxb", "http://example.test:8141", "other", "other"),
        ].map { profileID, serverURL, instanceID, branchID in
            LocalProfileModel(json: [
                "profile_id": profileID,
                "display_name": profileID.uppercased(),
                "server": ["base_url": serverURL],
                "workspaces": [[
                    "workspace_id": "w",
                    "server_workspace_ref": "workspace:w",
                    "access_mode": "owner",
                    "owner_ref": "18717974771",
                ]],
                "agents": [[
                    "agent_id": "research-\(profileID)",
                    "role": "research",
                    "scope": [
                        "instance_id": instanceID,
                        "branch_id": branchID,
                    ],
                ]],
                "research_records": [[
                    "record_id": "record-\(profileID)",
                    "agent_id": "research-\(profileID)",
                    "graph_instance_ref": "work-package:\(instanceID)",
                    "graph_branch_ref": "graph-branch:\(instanceID):\(branchID)",
                ]],
            ])
        }
        var requests: [(URL, String)] = []
        let controller = ResearchDirectoryController(
            profiles: profiles,
            load: { serverURL, workspaceRef in
                requests.append((serverURL, workspaceRef))
                return try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: listJSON().data(using: .utf8)!
                )
            }
        )

        await controller.refresh()

        XCTAssertEqual(requests.count, 1)
        XCTAssertEqual(requests.first?.0.absoluteString, "http://example.test:8141")
        XCTAssertEqual(requests.first?.1, "workspace:w")
        XCTAssertEqual(controller.items.count, 1)
        XCTAssertEqual(controller.items[0].profileIDs, ["maxa"])
        XCTAssertEqual(controller.items[0].profileNames, ["MAXA"])
        XCTAssertEqual(controller.items[0].summary.workPackageRef, "work-package:i")
    }

    @MainActor
    func testResearchDirectoryKeepsSameWorkspaceOnDifferentServersSeparate() async {
        let profiles = [
            ("maxa", "http://one.example.test:8141"),
            ("maxb", "http://two.example.test:8141"),
        ].map { profileID, serverURL in
            LocalProfileModel(json: [
                "profile_id": profileID,
                "display_name": profileID.uppercased(),
                "server": ["base_url": serverURL],
                "workspaces": [[
                    "workspace_id": "w",
                    "server_workspace_ref": "workspace:w",
                ]],
            ])
        }
        var requests = 0
        let controller = ResearchDirectoryController(
            profiles: profiles,
            load: { _, _ in
                requests += 1
                return try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: listJSON().data(using: .utf8)!
                )
            }
        )

        await controller.refresh()

        XCTAssertEqual(requests, 2)
        XCTAssertEqual(controller.items.count, 2)
        XCTAssertEqual(Set(controller.items.map(\.id)).count, 2)
    }

    @MainActor
    func testResearchDirectoryKeepsSuccessfulEndpointsOnPartialFailure() async {
        let profiles = [
            ("maxa", "http://good.example.test:8141"),
            ("maxb", "http://bad.example.test:8141"),
        ].map { profileID, serverURL in
            LocalProfileModel(json: [
                "profile_id": profileID,
                "display_name": profileID.uppercased(),
                "server": ["base_url": serverURL],
                "workspaces": [[
                    "workspace_id": profileID,
                    "server_workspace_ref": "workspace:\(profileID)",
                ]],
                "agents": [[
                    "agent_id": "research-\(profileID)",
                    "role": "research",
                    "scope": ["instance_id": "i", "branch_id": "b"],
                ]],
                "research_records": [[
                    "record_id": "record-\(profileID)",
                    "agent_id": "research-\(profileID)",
                    "graph_instance_ref": "work-package:i",
                    "graph_branch_ref": "graph-branch:i:b",
                ]],
            ])
        }
        let controller = ResearchDirectoryController(
            profiles: profiles,
            load: { serverURL, _ in
                if serverURL.host == "bad.example.test" {
                    throw APIError.transport("offline")
                }
                return try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: listJSON().data(using: .utf8)!
                )
            }
        )

        await controller.refresh()

        XCTAssertEqual(controller.items.count, 1)
        XCTAssertEqual(controller.items[0].profileIDs, ["maxa"])
        XCTAssertNotNil(controller.error)
    }

    func testWorkPackageTabUsesCanonicalResearchIdentity() throws {
        let page = try JSONDecoder().decode(
            ProfileResearchListResponse.self,
            from: listJSON().data(using: .utf8)!
        )
        let summary = try XCTUnwrap(page.items.first)
        let first = ResearchDirectoryItem(
            serverURL: URL(string: "http://one.example.test:8141")!,
            workspaceID: "w",
            workspaceRef: "workspace:w",
            profileIDs: ["maxa"],
            profileNames: ["MaxA"],
            summary: summary
        )
        let second = ResearchDirectoryItem(
            serverURL: URL(string: "http://two.example.test:8141")!,
            workspaceID: "w",
            workspaceRef: "workspace:w",
            profileIDs: ["maxa"],
            profileNames: ["MaxA"],
            summary: summary
        )

        XCTAssertEqual(ClientTab.workPackage(first).id, ClientTab.workPackage(first).id)
        XCTAssertNotEqual(ClientTab.workPackage(first).id, ClientTab.workPackage(second).id)
    }

    func testCheckpointLinksReportSectionsThroughStepEvidence() throws {
        let page = try JSONDecoder().decode(
            ProfileResearchTimelinePage.self,
            from: timelineJSON().data(using: .utf8)!
        )
        let step = try XCTUnwrap(page.items.first)
        let linked = ResearchReportSection(
            id: "section:linked",
            title: "Evidence",
            summary: "linked",
            links: [ResearchDeepLinkModel(json: [
                "link_id": "link:1",
                "kind": "evidence",
                "target_ref": "artifact:e",
                "section_ref": "section:linked",
            ])]
        )
        let unrelated = ResearchReportSection(
            id: "section:other",
            title: "Other",
            summary: "other",
            links: [ResearchDeepLinkModel(json: [
                "link_id": "link:2",
                "kind": "evidence",
                "target_ref": "artifact:other",
                "section_ref": "section:other",
            ])]
        )

        XCTAssertEqual(
            ResearchCheckpointLinker.relatedSections(
                to: step,
                among: [unrelated, linked]
            ).map(\.id),
            ["section:linked"]
        )
    }

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

private final class FakeProjectionTransport: ProfileResearchTransport {
    var responses: [ResearchHTTPResponse]
    var eventCount = 0
    var yieldsEvent = true
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
            if yieldsEvent { continuation.yield(()) }
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
        let controller = makeController(transport: transport)
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(controller.detail?.currentNode, "audit")
        XCTAssertEqual(controller.timeline.count, 1)
        XCTAssertEqual(transport.requests.count, 4)
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
        let controller = makeController(transport: transport)
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(transport.eventCount, 1)
        XCTAssertEqual(controller.detail?.currentNode, "completed")
        XCTAssertEqual(controller.timeline.count, 1)
    }

    func testConditionalProjectionHonorsMinimumIntervalAndPublishesCheckpoint() async {
        let changedDetail = response(
            detailJSON(
                refresh: #"{"mode":"stopped","terminal":true}"#,
                node: "completed",
                latestTraceRef: "trace:changed"
            ),
            etag: "\"detail-v2\""
        )
        let notModified = ResearchHTTPResponse(
            data: Data(), statusCode: 304, etag: "\"timeline-v1\""
        )
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh:
                    #"{"mode":"conditional_etag","minimum_interval_seconds":7,"only_while_visible":true,"terminal":false}"#
            ) + [changedDetail, notModified]
        )
        var slept: [TimeInterval] = []
        var checkpoints: [String] = []
        let controller = makeController(
            transport: transport,
            sleep: { slept.append($0) },
            onCheckpointChange: { checkpoints.append($0) }
        )
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(slept, [7])
        XCTAssertEqual(transport.requests.count, 6)
        XCTAssertEqual(checkpoints, ["trace:changed"])
    }

    func testSSEEndingBeforeTerminalFallsBackToBoundedConditionalRefresh() async {
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
            responses: fixtureResponses(
                detailRefresh:
                    #"{"mode":"job_sse","href":"/api/jobs/j/stream","terminal":false}"#
            ) + [changedDetail, notModified]
        )
        transport.yieldsEvent = false
        var slept: [TimeInterval] = []
        let controller = makeController(
            transport: transport,
            sleep: { slept.append($0) }
        )
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()
        XCTAssertEqual(transport.eventCount, 1)
        XCTAssertEqual(slept, [5])
        XCTAssertEqual(controller.detail?.currentNode, "completed")
    }

    func testPinnedWorkPackageSkipsDirectoryRequest() async throws {
        let page = try JSONDecoder().decode(
            ProfileResearchListResponse.self,
            from: listJSON().data(using: .utf8)!
        )
        let transport = FakeProjectionTransport(
            responses: [
                response(workPackageJSON(), etag: "\"work-package-v1\""),
                response(
                    detailJSON(refresh: #"{"mode":"stopped","terminal":true}"#),
                    etag: "\"detail-v1\""
                ),
                response(timelineJSON(), etag: "\"timeline-v1\""),
            ]
        )
        let profile = makeProfile()
        let controller = ProfileLiveProcessController(
            profile: profile,
            service: ProfileResearchService(
                baseURL: URL(string: "http://example.test")!,
                transport: transport
            ),
            pinnedSummary: try XCTUnwrap(page.items.first),
            initialWorkspaceID: "w"
        )
        await controller.observeSelectedResearch()

        XCTAssertEqual(transport.requests.count, 3)
        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/profile-research/work-package:i"
        )
        XCTAssertFalse(
            transport.requests.contains { $0.url?.path == "/api/profile-research" }
        )
    }

    private func makeController(
        transport: FakeProjectionTransport,
        sleep: @escaping @MainActor (TimeInterval) async throws -> Void = { _ in },
        onCheckpointChange: @escaping @MainActor (String) -> Void = { _ in }
    ) -> ProfileLiveProcessController {
        let profile = makeProfile()
        return ProfileLiveProcessController(
            profile: profile,
            service: ProfileResearchService(
                baseURL: URL(string: "http://example.test")!,
                transport: transport
            ),
            observationSleep: sleep,
            onCheckpointChange: onCheckpointChange
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
        response(workPackageJSON(), etag: "\"work-package-v1\""),
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
      "research_ref":"work-package:i","work_package_ref":"work-package:i",
      "workspace_ref":"workspace:w","product_group":"CNFutures",
      "status":"running","branch_count":1,"running_branch_count":1,
      "updated_at":1,"detail_href":"/api/profile-research/work-package:i",
      "report_lookup_ref":"work-package:i"}],
     "next_cursor":null,"etag":"sha256:list"}
    """
}

private func workPackageJSON() -> String {
    """
    {"success":true,"research_ref":"work-package:i",
     "work_package_ref":"work-package:i","product_group":"CNFutures",
     "mode":"live","branch_count":1,"omitted_branch_count":0,
     "branches":[{"research_ref":"work-package:i",
       "work_package_ref":"work-package:i","branch_ref":"graph-branch:i:b",
       "workspace_ref":"workspace:w","graph_ref":"factor-research@v6",
       "product_group":"CNFutures","mode":"live","label":"Primary",
       "current_node":"audit","status":"running",
       "trial_plan_ref":"trial-plan:t","latest_trace_ref":"trace:s",
       "lineage":{"relation":"fork",
         "source_branch_ref":"graph-branch:i:parent",
         "source_trace_ref":"trace:parent-step"},
       "created_at":1,"updated_at":1,
       "detail_href":"/api/profile-research/work-package:i/branches/b",
       "report_lookup_ref":"graph-branch:i:b"}],
     "report_lookup_ref":"work-package:i","etag":"sha256:work-package"}
    """
}

private func detailJSON(
    refresh: String,
    node: String = "audit",
    latestTraceRef: String = "trace:s"
) -> String {
    """
    {"success":true,"research_ref":"work-package:i",
     "work_package_ref":"work-package:i","branch_ref":"graph-branch:i:b",
     "label":"R",
     "current_node":"\(node)","status":"running",
     "trial_plan_ref":"trial-plan:t",
     "latest_trace_ref":"\(latestTraceRef)",
     "report_lookup_ref":"graph-branch:i:b",
     "evidence_refs":["artifact:e"],"omitted_evidence_count":0,
     "research_cycle":{"claims":[],"obligations":[{
       "obligation_ref":"obligation:o","status":"open",
       "materiality":"blocking","question_summary":"costs?"}],"closure":null},
     "job_refs":["job:j"],"run_refs":["run:r"],
     "timeline_href":"/api/profile-research/work-package:i/branches/b/timeline",
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
      "object_hrefs":["/api/research-graph-instances/i/branches/b/cycle-objects/obligation/o?trace_id=s"],
      "obligation_changes":[{"obligation_id":"o","from_state":"open",
      "to_state":"serviced"}],"claim_changes":[]}],
     "next_cursor":"older","etag":"sha256:timeline"}
    """
}
