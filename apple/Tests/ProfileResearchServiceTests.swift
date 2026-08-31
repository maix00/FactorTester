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

final class ProfileResearchServiceTests: SimplifiedChineseLocalizedTestCase {
    func testCanonicalResearchCatalogDecodesSharedAccessAndRelationships() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
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
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let detail = try await service.research(researchID: "research:v1:r1")

        XCTAssertEqual(detail.members.first?.profileRef, "maxb")
        XCTAssertEqual(detail.workspaces.first?.researchID, detail.researchID)
        XCTAssertEqual(detail.reports.first?.access.accessBasis, "report")
        XCTAssertTrue(detail.access.canDownload)
        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/research/research:v1:r1"
        )
    }

    func testCanonicalResearchCreationUsesSameEndpointAsServerWeb() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
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
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let research = try await service.createResearch(
            title: "新研究", description: "说明"
        )

        XCTAssertEqual(research.researchID, "research:v1:new")
        XCTAssertEqual(transport.requests.first?.httpMethod, "POST")
        XCTAssertEqual(transport.requests.first?.url?.path, "/api/research")
    }

    func testEntryRequirementAcceptsCanonicalCompactProjection() throws {
        let data = Data(
            """
            {
              "requirement_id":"factor_semantics.alternatives_and_falsifiers",
              "change_kind":"added",
              "resolution_status":"assessed_limited"
            }
            """.utf8
        )
        let item = try JSONDecoder().decode(
            ResearchEntryRequirementItem.self,
            from: data
        )
        XCTAssertEqual(
            item.titleZh,
            "factor_semantics.alternatives_and_falsifiers"
        )
        XCTAssertTrue(item.assessed)
    }

    func testStableWorkPackageOwnershipUsesCurrentPhysicalAgentScope() {
        let profile = LocalProfileModel(json: [
            "profile_id": "maxa",
            "display_name": "MaxA",
            "server": ["base_url": "http://example.test"],
            "agents": [[
                "agent_id": "research-maxa",
                "role": "research",
                "scope": [
                    "instance_id": "physical-v7",
                    "branch_id": "branch-v7",
                ],
            ]],
            "research_records": [[
                "record_id": "stable-work-package",
                "agent_id": "research-maxa",
                "graph_instance_ref": "work-package:stable-work-package",
                "graph_branch_ref": "graph-branch:physical-v7:branch-v7",
            ]],
        ])

        XCTAssertTrue(
            profile.owns(workPackageRef: "work-package:stable-work-package")
        )
    }

    func testResearchRecordUsesFactorScopeInsteadOfBroadProductGroupAsTitle() {
        let record = ResearchRecordModel(json: [
            "record_id": "stable-work-package",
            "title": "primary",
            "scope": [
                "factor_families": ["SgCCS"],
                "product_group": "china_futures",
                "research_role": "auxiliary_or_conditional_signal",
            ],
        ])

        XCTAssertEqual(record.preferredResearchTitle, "SgCCS · 辅助与条件信号研究")
        XCTAssertNotEqual(
            record.preferredResearchTitle,
            ResearchDisplayText.productGroup(record.productGroup)
        )
    }

    func testCurrentPhysicalBranchSelectsItsReportInsteadOfLastArtifact() {
        let record = ResearchRecordModel(json: [
            "record_id": "stable-work-package",
            "graph_branch_ref": "graph-branch:instance-v9:branch-v9",
            "artifacts": [
                reportArtifact(branchID: "branch-v9", suffix: "current"),
                reportArtifact(branchID: "branch-v6", suffix: "historical"),
            ],
        ])

        XCTAssertEqual(
            record.reportArtifact(branchID: "branch-v9")?.localRef,
            "file:///current"
        )
        XCTAssertEqual(record.currentReportArtifact?.localRef, "file:///current")
        XCTAssertEqual(
            record.reportArtifact(branchID: "branch-v6")?.localRef,
            "file:///historical"
        )
    }

    func testResearchDirectoryEmptyStatesDoNotConfuseLoadingWithNoProfile() {
        XCTAssertEqual(
            ProfileResearchEmptyState.loadingProfiles.message,
            "正在读取本地 Profile；暂不判断为空。"
        )
        XCTAssertEqual(
            ProfileResearchEmptyState.noWorkPackages.message,
            "已读取本地 Profile，但其绑定的工作区尚无 Work Package。"
        )
        XCTAssertNotEqual(
            ProfileResearchEmptyState.loadingProfiles,
            .noProfiles
        )
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
        XCTAssertEqual(
            step.objectHref(
                kind: "trial_plan",
                targetRef: "trial-plan:t"
            ),
            "/api/research-graph-instances/i/branches/b/"
                + "cycle-objects/trial_plan/t?trace_id=s"
        )
        XCTAssertEqual(
            step.objectHref(
                kind: "run_spec",
                targetRef: "runspec:sha256:hhhh"
            ),
            "/api/research-graph-instances/i/branches/b/"
                + "cycle-objects/run_spec/sha256:hhhh?trace_id=s"
        )
    }

    private func reportArtifact(
        branchID: String,
        suffix: String
    ) -> [String: Any] {
        [
            "artifact_ref": (
                "artifact:research/package/branches/\(branchID)/"
                + "authoring/HEAD.json"
            ),
            "format": "report_tree",
            "status": "ready",
            "local_ref": "file:///\(suffix)",
            "section_refs": [[
                "link_id": "chapter",
                "kind": "report_section",
                "target_ref": "node:trial",
                "section_ref": "chapter-trial",
            ]],
        ]
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

    func testFrozenTrialPlanJSONLoadsSubmittedBodyFromDirectRegistry() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
                """
                {"success":true,"trial_plan":{
                  "trial_plan_ref":"trial-plan:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  "trial_plan_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  "trial_plan":{"schema_version":1,"trial_plan_id":"plan-1",
                    "comparisons":[{"comparison_id":"main"}]}}}
                """,
                etag: "\"trial-plan\""
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let json = try await service.frozenObjectJSON(
            reference: ResearchDocumentTypedLink(
                kind: "trial_plan",
                targetRef: "trial-plan:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                label: "试验计划"
            )
        )

        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/trial-plans/direct/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        let value = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(json.utf8))
                as? [String: Any]
        )
        XCTAssertEqual(value["trial_plan_id"] as? String, "plan-1")
        XCTAssertNil(value["trial_plan_hash"])
    }

    func testFrozenRunSpecJSONLoadsSubmittedBodyFromOwnerRegistry() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
                """
                {"success":true,"run_spec":{
                  "run_spec_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                  "run_spec_version":2,
                  "run_spec":{"run_spec_version":2,"analyses":["ic"],
                    "configuration":{"schema_version":1}}}}
                """,
                etag: "\"run-spec\""
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let json = try await service.frozenObjectJSON(
            reference: ResearchDocumentTypedLink(
                kind: "run_spec",
                targetRef: "runspec:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                label: "运行配置"
            )
        )

        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/run-specs/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        )
        let value = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(json.utf8))
                as? [String: Any]
        )
        XCTAssertEqual(value["analyses"] as? [String], ["ic"])
        XCTAssertNil(value["run_spec_hash"])
    }

    func testFrozenRunJSONLoadsTheRunSubmittedRunSpec() async throws {
        let transport = FakeProjectionTransport(responses: [
            response(
                """
                {"success":true,"run":{
                  "run_id":"run-1",
                  "run_spec":{"run_spec_version":2,"analyses":["group"],
                    "configuration":{"schema_version":1}}}}
                """,
                etag: "\"run\""
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let json = try await service.frozenObjectJSON(
            reference: ResearchDocumentTypedLink(
                kind: "run",
                targetRef: "run:run-1",
                label: "运行"
            )
        )

        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/runs/run-1"
        )
        let value = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(json.utf8))
                as? [String: Any]
        )
        XCTAssertEqual(value["analyses"] as? [String], ["group"])
        XCTAssertNil(value["run_id"])
    }

    func testAuditObjectDecodesTrialPlanAndEvidenceDetails() throws {
        let plan = try JSONDecoder().decode(
            ResearchAuditObjectEnvelope.self,
            from: Data(
                """
                {"object":{"schema_version":1,"trial_plan_id":"plan-1","version":4,"hypothesis_ref":"hypothesis-1","trial_family":"family-1","protocol_ref":"cross-sectional-ic@1","outcomes":{"primary":["rank-ic"],"secondary":["coverage"]},"sample_roles":[{"sample_ref":"selection-2020-2023","role":"selection"}]}}
                """.utf8
            )
        ).object
        let evidence = try JSONDecoder().decode(
            ResearchAuditObjectEnvelope.self,
            from: Data(
                """
                {"object":{"schema_version":2,"envelope_id":"job-attempt:j","evidence_kind":"job_attempt","envelope_hash":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","source_refs":["research-job:j"],"metric_refs":["result-summary:r"],"artifact_refs":["artifact:a"],"hypotheses_tested":1,"stop_condition":null,"limitations":["Limited window."],"conflicts":[]}}
                """.utf8
            )
        ).object

        XCTAssertEqual(plan.trialPlanID, "plan-1")
        XCTAssertEqual(plan.outcomes?.primary, ["rank-ic"])
        XCTAssertEqual(plan.sampleRoles?.first?.role, "selection")
        XCTAssertEqual(evidence.evidenceKind, "job_attempt")
        XCTAssertEqual(evidence.metricRefs, ["result-summary:r"])
        XCTAssertEqual(evidence.limitations, ["Limited window."])
    }

    func testAuditObjectDecodesImmutableRunConfiguration() throws {
        let run = try JSONDecoder().decode(
            ResearchAuditObjectEnvelope.self,
            from: Data(
                """
                {"object":{"schema_version":1,"object_kind":"run","run_id":"run-1","configuration_id":"config-1","configuration_revision":7,"run_spec_version":2,"run_spec_hash":"hhhh","run_spec_json":"{\\n  \\"end_session_skip\\": false\\n}","trial_role":"candidate","trial_stage":"selection","comparison_id":"comparison-1","sample_ref":"sample-1","sample_start":"2024-01-01","sample_end":"2025-12-31"}}
                """.utf8
            )
        ).object

        XCTAssertEqual(run.runID, "run-1")
        XCTAssertEqual(run.configurationRevision, 7)
        XCTAssertEqual(run.runSpecVersion, 2)
        XCTAssertEqual(run.trialRole, "candidate")
        XCTAssertTrue(run.runSpecJSON?.contains("end_session_skip") == true)
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

    func testWorkPackageDecodesBoundedVersionTreeNodesAndEdges() throws {
        let tree = #"""
        "tree":{"schema_version":2,"nodes":[{
          "node_ref":"trace:s","checkpoint_ref":"trace:s",
          "trace_ref":"trace:s","branch_ref":"graph-branch:i:b",
          "navigation_branch_id":"b",
          "edge_ref":"edge:e","from_node":"trial","to_node":"audit",
          "created_at":1,"status":"running","is_head":true,
          "is_root":true,"sequence_rank":1,"history_rank":1
        }],"edges":[{
          "edge_ref":"lineage:b:trace:s","relation":"fork",
          "source_node_ref":"trace:parent-step",
          "target_node_ref":"trace:s",
          "source_branch_ref":"graph-branch:i:parent",
          "target_branch_ref":"graph-branch:i:b"
        }],"omitted_node_count":4},
        """#
        let json = workPackageJSON().replacingOccurrences(
            of: #""report_lookup_ref":"work-package:i""#,
            with: tree + #""report_lookup_ref":"work-package:i""#
        )
        let detail = try JSONDecoder().decode(
            ProfileResearchWorkPackageDetail.self,
            from: json.data(using: .utf8)!
        )
        let node = try XCTUnwrap(detail.tree?.nodes.first)
        XCTAssertEqual(node.checkpointRef, "trace:s")
        XCTAssertEqual(node.navigationBranchID, "b")
        XCTAssertTrue(node.isHead)
        XCTAssertEqual(detail.tree?.edges.first?.relation, "fork")
        XCTAssertEqual(detail.tree?.omittedNodeCount, 4)
    }

    @MainActor
    func testResearchDirectoryLoadsOwnerWideOnceAndAssignsExactProfile() async {
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
                ], [
                    "workspace_id": "extra-\(profileID)",
                    "server_workspace_ref": "workspace:extra-\(profileID)",
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
        XCTAssertEqual(requests.first?.1, "")
        XCTAssertEqual(controller.items.count, 1)
        XCTAssertEqual(controller.items[0].profileIDs, ["maxa"])
        XCTAssertEqual(controller.items[0].profileNames, ["MAXA"])
        XCTAssertEqual(controller.items[0].summary.workPackageRef, "work-package:i")
    }

    @MainActor
    func testResearchDirectoryUsesServerTitleInsteadOfProductGroupFallback() async throws {
        let profile = LocalProfileModel(json: [
            "profile_id": "maxa",
            "display_name": "MaxA",
            "server": ["base_url": "http://example.test:8141"],
            "workspaces": [[
                "workspace_id": "w",
                "server_workspace_ref": "workspace:w",
            ]],
        ])
        let titled = listJSON().replacingOccurrences(
            of: #""product_group":"CNFutures""#,
            with: #""title":"动量因子辅助研究","product_group":"CNFutures""#
        )
        let controller = ResearchDirectoryController(
            profiles: [profile],
            load: { _, _ in
                try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: titled.data(using: .utf8)!
                )
            }
        )

        await controller.refresh()

        XCTAssertEqual(controller.items.first?.displayTitle, "动量因子辅助研究")
    }

    @MainActor
    func testResearchDirectoryDoesNotPresentProductGroupAsResearchTitle() async throws {
        let profile = LocalProfileModel(json: [
            "profile_id": "maxa",
            "display_name": "MaxA",
            "server": ["base_url": "http://example.test:8141"],
            "workspaces": [[
                "workspace_id": "w",
                "server_workspace_ref": "workspace:w",
            ]],
        ])
        let controller = ResearchDirectoryController(
            profiles: [profile],
            load: { _, _ in
                try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: listJSON().data(using: .utf8)!
                )
            }
        )

        await controller.refresh()

        XCTAssertEqual(controller.items.first?.displayTitle, "未命名研究")
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
            displayTitle: "SgCCS · 辅助与条件信号研究",
            scopeSummary: "SgCCS · 辅助与条件信号研究",
            summary: summary
        )
        let second = ResearchDirectoryItem(
            serverURL: URL(string: "http://two.example.test:8141")!,
            workspaceID: "w",
            workspaceRef: "workspace:w",
            profileIDs: ["maxa"],
            profileNames: ["MaxA"],
            displayTitle: "SgCCS · 辅助与条件信号研究",
            scopeSummary: "SgCCS · 辅助与条件信号研究",
            summary: summary
        )

        XCTAssertEqual(ClientTab.workPackage(first).id, ClientTab.workPackage(first).id)
        XCTAssertNotEqual(ClientTab.workPackage(first).id, ClientTab.workPackage(second).id)
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

    func testStructuredProjectionFailurePreservesServerMessage() async {
        let transport = FakeProjectionTransport(responses: [
            ResearchHTTPResponse(
                data: Data(
                    """
                    {"success":false,
                     "error":"研究投影暂时无法读取，请稍后重试。",
                     "error_code":"research_projection_failed"}
                    """.utf8
                ),
                statusCode: 500,
                etag: nil
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        do {
            _ = try await service.workPackageDetail(
                href: "/api/profile-research/work-package:i"
            )
            XCTFail("expected a structured projection failure")
        } catch {
            XCTAssertEqual(
                (error as? APIError)?.errorDescription,
                "研究投影暂时无法读取，请稍后重试。"
            )
        }
    }

    func testStructuredProjection404IsShown() async {
        let transport = FakeProjectionTransport(responses: [
            ResearchHTTPResponse(
                data: Data(
                    """
                    {"success":false,"error":"profile research not found"}
                    """.utf8
                ),
                statusCode: 404,
                etag: nil
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        do {
            _ = try await service.workPackageDetail(
                href: "/api/profile-research/work-package:missing"
            )
            XCTFail("expected not-found projection failure")
        } catch {
            XCTAssertEqual(
                (error as? APIError)?.errorDescription,
                "profile research not found"
            )
        }
    }

    func testProjectionDecodeFailureExplainsProtocolMismatch() async {
        let transport = FakeProjectionTransport(responses: [
            ResearchHTTPResponse(
                data: Data(#"{"success":true,"schema_version":999}"#.utf8),
                statusCode: 200,
                etag: nil
            ),
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        do {
            _ = try await service.workPackageDetail(
                href: "/api/profile-research/work-package:i"
            )
            XCTFail("expected projection decode failure")
        } catch {
            XCTAssertEqual(
                (error as? APIError)?.errorDescription,
                "研究投影格式无法识别；客户端与服务器协议版本可能不一致。"
            )
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

    func testResearchListRequestsOneLifecycleProjection() async throws {
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
            XCTAssertEqual(values["workspace_ref"], "workspace:w")
            XCTAssertEqual(values["lifecycle"], "archived")
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200,
                    httpVersion: nil, headerFields: nil
                )!,
                listJSON().data(using: .utf8)!
            )
        }
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: URLSessionProfileResearchTransport(session: session)
        )

        let page = try await service.list(
            workspaceRef: "workspace:w",
            lifecycle: "archived"
        )

        XCTAssertEqual(page.items.count, 1)
    }

    func testResearchListOmitsWorkspaceFilterForOwnerWideDirectory() async throws {
        let session = stubSession()
        StubURLProtocol.handler = { request in
            let components = URLComponents(
                url: request.url!,
                resolvingAgainstBaseURL: false
            )
            let names = Set(components?.queryItems?.map(\.name) ?? [])
            XCTAssertFalse(names.contains("workspace_ref"))
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200,
                    httpVersion: nil, headerFields: nil
                )!,
                listJSON().data(using: .utf8)!
            )
        }
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: URLSessionProfileResearchTransport(session: session)
        )

        _ = try await service.list()
    }

    func testLifecycleMutationUsesPatchAndRevisionCAS() async throws {
        let transport = FakeProjectionTransport(responses: [
            ResearchHTTPResponse(
                data: Data("""
                {"success":true,"work_package_ref":"work-package:i",
                 "lifecycle":"archived","revision":8,"updated_at":2}
                """.utf8),
                statusCode: 200,
                etag: nil
            )
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://example.test")!,
            transport: transport
        )

        let result = try await service.transitionLifecycle(
            workPackageRef: "work-package:i",
            target: "archived",
            expectedRevision: 7,
            reason: "用户归档"
        )

        XCTAssertEqual(result.lifecycle, "archived")
        XCTAssertEqual(result.revision, 8)
        let request = try XCTUnwrap(transport.requests.first)
        XCTAssertEqual(request.httpMethod, "PATCH")
        XCTAssertTrue(request.url!.path.hasSuffix(
            "/api/profile-research/work-package:i/lifecycle"
        ))
        let body = try JSONSerialization.jsonObject(
            with: try XCTUnwrap(request.httpBody)
        ) as! [String: Any]
        XCTAssertEqual(body["target"] as? String, "archived")
        XCTAssertEqual(body["expected_revision"] as? Int, 7)
    }

    func testManagerRoutedServicePreservesPathPortAndAuthentication() async throws {
        let transport = FakeProjectionTransport(responses: [
            ResearchHTTPResponse(
                data: listJSON().data(using: .utf8)!,
                statusCode: 200,
                etag: nil
            )
        ])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://127.0.0.1:7998")!,
            transport: transport,
            servicePort: 8141,
            managerToken: "manager-user-token"
        )

        _ = try await service.list(lifecycle: "active")

        let request = try XCTUnwrap(transport.requests.first)
        XCTAssertEqual(request.url?.port, 7998)
        XCTAssertEqual(request.url?.path, "/api/profile-research")
        XCTAssertEqual(
            URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "port" })?.value,
            "8141"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer manager-user-token"
        )
    }

    func testManagerRoutedServiceKeepsSSEOnUnifiedManagerOrigin() async throws {
        let transport = FakeProjectionTransport(responses: [])
        let service = ProfileResearchService(
            baseURL: URL(string: "http://127.0.0.1:7998")!,
            transport: transport,
            servicePort: 8141,
            managerToken: "manager-user-token"
        )

        for try await _ in service.events(href: "/api/jobs/one/events") {}

        let request = try XCTUnwrap(transport.requests.first)
        XCTAssertEqual(request.url?.port, 7998)
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer manager-user-token"
        )
        XCTAssertTrue(request.url?.query?.contains("port=8141") == true)
    }

    @MainActor
    func testResearchDirectoryForwardsSelectedLifecycle() async {
        let profile = LocalProfileModel(json: [
            "profile_id": "maxa",
            "display_name": "MaxA",
            "server": ["base_url": "http://example.test:8141"],
            "workspaces": [[
                "workspace_id": "w",
                "server_workspace_ref": "workspace:w",
            ]],
        ])
        var requestedLifecycle = ""
        let controller = ResearchDirectoryController(
            profiles: [profile],
            lifecycleLoad: { _, _, lifecycle in
                requestedLifecycle = lifecycle
                return try JSONDecoder().decode(
                    ProfileResearchListResponse.self,
                    from: listJSON().data(using: .utf8)!
                )
            }
        )

        await controller.refresh(lifecycle: .deleted)

        XCTAssertEqual(requestedLifecycle, "deleted")
        XCTAssertEqual(controller.lifecycle, .deleted)
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
final class ProfileLiveProcessControllerTests: SimplifiedChineseLocalizedTestCase {
    func testControllerStartsFromRememberedBranchID() {
        let controller = ProfileLiveProcessController(
            profile: makeProfile(),
            initialBranchID: "remembered-branch"
        )

        XCTAssertEqual(controller.selectedBranchID, "remembered-branch")
    }

    func testReadableReportHistoryLoadsTimelinePagesUntilCheckpointCovered() async {
        let older = response(
            """
            {"success":true,"research_ref":"graph-branch:i:b","items":[{
              "step_ref":"trace:root","edge_ref":"graph-edge:root",
              "from_node":"start","to_node":"trial","created_at":0,
              "evidence_refs":[],"trial_plan_refs":[],
              "obligation_refs":[],"claim_refs":[],
              "job_refs":[],"run_refs":[],"object_hrefs":[],
              "obligation_changes":[],"claim_changes":[]}],
             "next_cursor":null,"etag":"sha256:older"}
            """,
            etag: "\"timeline-v0\""
        )
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh: #"{"mode":"stopped","terminal":true}"#
            ) + [older]
        )
        let controller = makeController(transport: transport)
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()

        await controller.loadTimeline(
            through: ["trace:root", "trace:s"]
        )

        XCTAssertEqual(
            Set(controller.timeline.map(\.stepRef)),
            ["trace:root", "trace:s"]
        )
        XCTAssertNil(controller.nextTimelineCursor)
        XCTAssertEqual(
            transport.requests.last?.url?.query?
                .contains("after=older"),
            true
        )
    }

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

    func testInitialCheckpointRefreshesProfileWhenPhysicalBranchIsNew() async {
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh: #"{"mode":"stopped","terminal":true}"#
            )
        )
        var checkpoints: [String] = []
        let controller = makeController(
            transport: transport,
            onCheckpointChange: { checkpoints.append($0) }
        )

        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()

        XCTAssertEqual(checkpoints, ["trace:s"])
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
        let refreshedWorkPackage = response(
            workPackageJSON(), etag: "\"work-package-v2\""
        )
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh:
                    #"{"mode":"conditional_etag","minimum_interval_seconds":7,"only_while_visible":true,"terminal":false}"#
            ) + [changedDetail, refreshedWorkPackage, notModified]
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
        XCTAssertEqual(transport.requests.count, 7)
        XCTAssertEqual(
            transport.requests.filter {
                $0.url?.path == "/api/profile-research/work-package:i"
            }.count,
            2
        )
        XCTAssertEqual(
            transport.requests[5].value(forHTTPHeaderField: "If-None-Match"),
            "\"work-package-v1\""
        )
        XCTAssertEqual(checkpoints, ["trace:s", "trace:changed"])
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

        XCTAssertEqual(controller.workPackage?.branches.count, 1)
        XCTAssertEqual(controller.selectedBranchID, "b")
        XCTAssertEqual(controller.selectedBranch?.branchID, "b")
        XCTAssertEqual(transport.requests.count, 3)
        XCTAssertEqual(
            transport.requests.first?.url?.path,
            "/api/profile-research/work-package:i"
        )
        XCTAssertFalse(
            transport.requests.contains { $0.url?.path == "/api/profile-research" }
        )
    }

    func testMissingNavigationBranchEndsLoadingWithUsefulError() async {
        let transport = FakeProjectionTransport(
            responses: fixtureResponses(
                detailRefresh: #"{"mode":"stopped","terminal":true}"#
            )
        )
        let controller = makeController(transport: transport)
        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()

        controller.selectedBranchID = "stale-physical-v7"
        await controller.observeSelectedResearch()

        XCTAssertNil(controller.detail)
        XCTAssertFalse(controller.isLoading)
        XCTAssertEqual(
            controller.error,
            "研究路径指向的分支不在当前工作包中，请刷新研究目录后重试。"
        )
    }

    func testEmptyTimelineCompletesAsSuccessfulEmptyState() async {
        let emptyTimeline = response(
            """
            {"success":true,"research_ref":"graph-branch:i:b",
             "items":[],"next_cursor":null,"etag":"sha256:empty"}
            """,
            etag: "\"timeline-empty\""
        )
        var responses = fixtureResponses(
            detailRefresh: #"{"mode":"stopped","terminal":true}"#
        )
        responses[3] = emptyTimeline
        let controller = makeController(
            transport: FakeProjectionTransport(responses: responses)
        )

        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()

        XCTAssertNotNil(controller.detail)
        XCTAssertTrue(controller.timeline.isEmpty)
        XCTAssertNil(controller.error)
        XCTAssertFalse(controller.isLoadingResearch)
    }

    func testTimelineFailureDoesNotBlockResearchDetailOrLocalReport() async {
        let failedTimeline = ResearchHTTPResponse(
            data: #"{"success":false,"error":"timeline replay failed"}"#
                .data(using: .utf8)!,
            statusCode: 400,
            etag: nil
        )
        var responses = fixtureResponses(
            detailRefresh: #"{"mode":"stopped","terminal":true}"#
        )
        responses[3] = failedTimeline
        let controller = makeController(
            transport: FakeProjectionTransport(responses: responses)
        )

        await controller.loadSelectedWorkspace()
        await controller.observeSelectedResearch()

        XCTAssertNotNil(controller.workPackage)
        XCTAssertNotNil(controller.detail)
        XCTAssertTrue(controller.timeline.isEmpty)
        XCTAssertNil(controller.error)
        XCTAssertNotNil(controller.timelineError)
        XCTAssertFalse(controller.isLoadingResearch)
    }

    func testCancelledObservationTerminatesOnlyCurrentLoadingState() async {
        var enteredObservationWait = false
        let controller = makeController(
            transport: FakeProjectionTransport(
                responses: fixtureResponses(
                    detailRefresh:
                        #"{"mode":"conditional_etag","minimum_interval_seconds":30,"terminal":false}"#
                )
            ),
            sleep: { _ in
                enteredObservationWait = true
                try await Task.sleep(nanoseconds: 30_000_000_000)
            }
        )
        await controller.loadSelectedWorkspace()
        let observation = Task {
            await controller.observeSelectedResearch()
        }
        for _ in 0..<200 where !enteredObservationWait {
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertTrue(
            enteredObservationWait,
            "observation did not enter conditional refresh wait"
        )
        observation.cancel()
        await observation.value

        XCTAssertFalse(controller.isLoadingResearch)
        XCTAssertEqual(
            controller.error,
            "研究过程读取已取消；可重新选择检查点或刷新研究。"
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
    {"success":true,"workspace_ref":"workspace:w","lifecycle":"active","items":[{
      "research_ref":"work-package:i","work_package_ref":"work-package:i",
      "workspace_ref":"workspace:w","product_group":"CNFutures",
      "status":"running","lifecycle":"active","lifecycle_revision":1,
      "branch_count":1,"running_branch_count":1,
      "updated_at":1,"detail_href":"/api/profile-research/work-package:i",
      "report_lookup_ref":"work-package:i"}],
     "next_cursor":null,"etag":"sha256:list"}
    """
}

private func workPackageJSON() -> String {
    """
    {"success":true,"research_ref":"work-package:i",
     "work_package_ref":"work-package:i","product_group":"CNFutures",
     "mode":"live","lifecycle":"active","lifecycle_revision":1,
     "branch_count":1,"omitted_branch_count":0,
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
       "title_zh":"成本覆盖","materiality":"blocking",
       "question_summary":"costs?"}],"closure":null},
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
      "run_spec_refs":["runspec:sha256:hhhh"],
      "obligation_refs":["obligation:o"],"claim_refs":[],
      "job_refs":["job:j"],"run_refs":["run:r"],
      "object_hrefs":["/api/research-graph-instances/i/branches/b/cycle-objects/obligation/o?trace_id=s","/api/research-graph-instances/i/branches/b/cycle-objects/trial_plan/t?trace_id=s","/api/research-graph-instances/i/branches/b/cycle-objects/run_spec/sha256:hhhh?trace_id=s"],
      "obligation_changes":[{"obligation_id":"o","from_state":"open",
      "to_state":"serviced"}],"claim_changes":[]}],
     "next_cursor":"older","etag":"sha256:timeline"}
    """
}
