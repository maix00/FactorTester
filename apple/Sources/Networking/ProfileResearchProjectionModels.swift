import Foundation

struct ProfileResearchListResponse: Decodable {
    let workspaceRef: String
    let lifecycle: String?
    let items: [ProfileResearchSummary]
    let nextCursor: String?
    let etag: String

    enum CodingKeys: String, CodingKey {
        case workspaceRef = "workspace_ref"
        case lifecycle
        case items
        case nextCursor = "next_cursor"
        case etag
    }
}

struct ProfileResearchProductScope: Decodable {
    let kind: String
    let productGroup: String
    let universe: [String]?
    let productMask: [String]?
    let universeDefinedIn: String?

    enum CodingKeys: String, CodingKey {
        case kind
        case productGroup = "product_group"
        case universe
        case productMask = "product_mask"
        case universeDefinedIn = "universe_defined_in"
    }
}

struct ProfileResearchSummary: Decodable, Identifiable {
    let researchRef: String
    let workPackageRef: String
    let workspaceRef: String
    let title: String?
    let productGroup: String
    let productScope: ProfileResearchProductScope?
    let status: String
    let branchCount: Int
    let runningBranchCount: Int
    let updatedAt: Double
    let detailHref: String
    let reportLookupRef: String?
    let createdByProfileRef: String?
    let currentOwnerProfileRef: String?
    let lifecycle: String?
    let lifecycleRevision: Int?
    var id: String { researchRef }

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case workPackageRef = "work_package_ref"
        case workspaceRef = "workspace_ref"
        case title
        case productGroup = "product_group"
        case productScope = "product_scope"
        case status
        case branchCount = "branch_count"
        case runningBranchCount = "running_branch_count"
        case updatedAt = "updated_at"
        case detailHref = "detail_href"
        case reportLookupRef = "report_lookup_ref"
        case createdByProfileRef = "created_by_profile_ref"
        case currentOwnerProfileRef = "current_owner_profile_ref"
        case lifecycle
        case lifecycleRevision = "lifecycle_revision"
    }
}

struct ProfileResearchWorkPackageDetail: Decodable {
    let researchRef: String
    let workPackageRef: String
    let productGroup: String
    let productScope: ProfileResearchProductScope?
    let mode: String
    let branchCount: Int
    let omittedBranchCount: Int
    let branches: [ProfileResearchBranchSummary]
    let tree: ResearchVersionTreeProjection?
    let reportLookupRef: String?
    let etag: String
    let lifecycle: String?
    let lifecycleRevision: Int?

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case workPackageRef = "work_package_ref"
        case productGroup = "product_group"
        case productScope = "product_scope"
        case mode
        case branchCount = "branch_count"
        case omittedBranchCount = "omitted_branch_count"
        case branches
        case tree
        case reportLookupRef = "report_lookup_ref"
        case etag
        case lifecycle
        case lifecycleRevision = "lifecycle_revision"
    }
}

struct ProfileResearchLifecycleResult: Decodable {
    let workPackageRef: String
    let lifecycle: String
    let revision: Int
    let updatedAt: Double

    enum CodingKeys: String, CodingKey {
        case workPackageRef = "work_package_ref"
        case lifecycle
        case revision
        case updatedAt = "updated_at"
    }
}

/// A bounded relationship projection for the Git-like navigator.  It carries
/// checkpoint references and real lineage edges only; report prose remains in
/// the verified journal loaded by the report view.
struct ResearchVersionTreeProjection: Decodable {
    let schemaVersion: Int
    let nodes: [ResearchVersionTreeNode]
    let edges: [ResearchVersionTreeEdge]
    let omittedNodeCount: Int

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case nodes
        case edges
        case omittedNodeCount = "omitted_node_count"
    }
}

struct ResearchVersionTreeNode: Decodable, Identifiable {
    let nodeRef: String
    let checkpointRef: String
    let traceRef: String
    let branchRef: String
    let navigationBranchID: String
    let graphRef: String
    let edgeRef: String
    let fromNode: String
    let toNode: String
    let createdAt: Double
    let status: String
    let isHead: Bool
    let isRoot: Bool
    let sequenceRank: Int
    let historyRank: Int

    var id: String { nodeRef }

    enum CodingKeys: String, CodingKey {
        case nodeRef = "node_ref"
        case checkpointRef = "checkpoint_ref"
        case traceRef = "trace_ref"
        case branchRef = "branch_ref"
        case navigationBranchID = "navigation_branch_id"
        case graphRef = "graph_ref"
        case edgeRef = "edge_ref"
        case fromNode = "from_node"
        case toNode = "to_node"
        case createdAt = "created_at"
        case status
        case isHead = "is_head"
        case isRoot = "is_root"
        case sequenceRank = "sequence_rank"
        case historyRank = "history_rank"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        checkpointRef = try values.decode(String.self, forKey: .checkpointRef)
        nodeRef = try values.decodeIfPresent(
            String.self, forKey: .nodeRef
        ) ?? checkpointRef
        traceRef = try values.decodeIfPresent(
            String.self, forKey: .traceRef
        ) ?? checkpointRef
        branchRef = try values.decode(String.self, forKey: .branchRef)
        navigationBranchID = try values.decode(
            String.self, forKey: .navigationBranchID
        )
        graphRef = try values.decodeIfPresent(
            String.self, forKey: .graphRef
        ) ?? ""
        edgeRef = try values.decode(String.self, forKey: .edgeRef)
        fromNode = try values.decode(String.self, forKey: .fromNode)
        toNode = try values.decode(String.self, forKey: .toNode)
        createdAt = try values.decode(Double.self, forKey: .createdAt)
        status = try values.decode(String.self, forKey: .status)
        isHead = try values.decode(Bool.self, forKey: .isHead)
        isRoot = try values.decode(Bool.self, forKey: .isRoot)
        sequenceRank = try values.decodeIfPresent(
            Int.self, forKey: .sequenceRank
        ) ?? 0
        historyRank = try values.decodeIfPresent(
            Int.self, forKey: .historyRank
        ) ?? 0
    }
}

struct ResearchVersionTreeEdge: Decodable, Identifiable {
    let edgeRef: String
    let relation: String
    let sourceNodeRef: String
    let targetNodeRef: String
    let sourceBranchRef: String
    let targetBranchRef: String

    var id: String { edgeRef }

    enum CodingKeys: String, CodingKey {
        case edgeRef = "edge_ref"
        case relation
        case sourceNodeRef = "source_node_ref"
        case targetNodeRef = "target_node_ref"
        case sourceBranchRef = "source_branch_ref"
        case targetBranchRef = "target_branch_ref"
    }
}

struct ProfileResearchBranchSummary: Decodable, Identifiable {
    let branchRef: String
    let label: String
    let currentNode: String
    let status: String
    let trialPlanRef: String?
    let latestTraceRef: String?
    let lineage: ResearchBranchLineage?
    let createdAt: Double
    let updatedAt: Double
    let detailHref: String
    let reportLookupRef: String?
    let createdByProfileRef: String?
    let currentOwnerProfileRef: String?
    let latestActingProfileRef: String?
    var id: String { branchRef }

    var branchID: String {
        branchRef.split(separator: ":").last.map(String.init) ?? branchRef
    }

    enum CodingKeys: String, CodingKey {
        case branchRef = "branch_ref"
        case label
        case currentNode = "current_node"
        case status
        case trialPlanRef = "trial_plan_ref"
        case latestTraceRef = "latest_trace_ref"
        case lineage
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case detailHref = "detail_href"
        case reportLookupRef = "report_lookup_ref"
        case createdByProfileRef = "created_by_profile_ref"
        case currentOwnerProfileRef = "current_owner_profile_ref"
        case latestActingProfileRef = "latest_acting_profile_ref"
    }
}

struct ResearchBranchLineage: Decodable {
    let relation: String
    let sourceBranchRef: String?
    let sourceTraceRef: String?
    let sourceCheckpointHash: String?

    enum CodingKeys: String, CodingKey {
        case relation
        case sourceBranchRef = "source_branch_ref"
        case sourceTraceRef = "source_trace_ref"
        case sourceCheckpointHash = "source_checkpoint_hash"
    }
}

struct ProfileResearchDetail: Decodable {
    let researchRef: String
    let workPackageRef: String
    let branchRef: String
    let label: String
    let currentNode: String
    let status: String
    let trialPlanRef: String?
    let latestTraceRef: String?
    let reportLookupRef: String?
    let evidenceRefs: [String]
    let omittedEvidenceCount: Int
    let researchCycle: ResearchCycleProjection
    let jobRefs: [String]
    let runRefs: [String]
    let timelineHref: String
    let refresh: ResearchRefreshDirective
    let etag: String
    let createdByProfileRef: String?
    let currentOwnerProfileRef: String?
    let latestActingProfileRef: String?

    var branchID: String {
        branchRef.split(separator: ":").last.map(String.init) ?? branchRef
    }

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case workPackageRef = "work_package_ref"
        case branchRef = "branch_ref"
        case label
        case currentNode = "current_node"
        case status
        case trialPlanRef = "trial_plan_ref"
        case latestTraceRef = "latest_trace_ref"
        case reportLookupRef = "report_lookup_ref"
        case evidenceRefs = "evidence_refs"
        case omittedEvidenceCount = "omitted_evidence_count"
        case researchCycle = "research_cycle"
        case jobRefs = "job_refs"
        case runRefs = "run_refs"
        case timelineHref = "timeline_href"
        case refresh
        case etag
        case createdByProfileRef = "created_by_profile_ref"
        case currentOwnerProfileRef = "current_owner_profile_ref"
        case latestActingProfileRef = "latest_acting_profile_ref"
    }
}

struct ResearchCycleProjection: Decodable {
    let claims: [ResearchClaimProjection]
    let obligations: [ResearchObligationProjection]
    let closure: ResearchClosureProjection?
}

struct ResearchClaimProjection: Decodable, Identifiable {
    let claimRef: String
    let claimType: String
    let evidenceState: String
    var id: String { claimRef }
    enum CodingKeys: String, CodingKey {
        case claimRef = "claim_ref"
        case claimType = "claim_type"
        case evidenceState = "evidence_state"
    }
}

struct ResearchObligationProjection: Decodable, Identifiable {
    let obligationRef: String
    let titleZH: String
    let status: String
    let materiality: String
    let questionSummary: String
    var id: String { obligationRef }
    enum CodingKeys: String, CodingKey {
        case obligationRef = "obligation_ref"
        case titleZH = "title_zh"
        case status, materiality
        case questionSummary = "question_summary"
    }
}

struct ResearchObligationPresentation: Decodable, Identifiable {
    let obligationRef: String
    let titleZH: String
    let questionSummary: String
    var id: String { obligationRef }

    enum CodingKeys: String, CodingKey {
        case obligationRef = "obligation_ref"
        case titleZH = "title_zh"
        case questionSummary = "question_summary"
    }
}

struct ResearchEvidencePresentation: Decodable, Identifiable {
    let evidenceRef: String
    let title: String
    let claimSummary: String
    var id: String { evidenceRef }

    enum CodingKeys: String, CodingKey {
        case evidenceRef = "evidence_ref"
        case title
        case claimSummary = "claim_summary"
    }
}

struct ResearchClosureProjection: Decodable {
    let proposalRef: String?
    let disposition: String
    enum CodingKeys: String, CodingKey {
        case proposalRef = "proposal_ref"
        case disposition
    }
}

struct ResearchRefreshDirective: Decodable {
    let mode: String
    let href: String?
    let minimumIntervalSeconds: Double?
    let onlyWhileVisible: Bool?
    let terminal: Bool
    enum CodingKeys: String, CodingKey {
        case mode, href, terminal
        case minimumIntervalSeconds = "minimum_interval_seconds"
        case onlyWhileVisible = "only_while_visible"
    }
}

struct ProfileResearchTimelinePage: Decodable {
    let researchRef: String
    let items: [ResearchTransitionStep]
    let nextCursor: String?
    let etag: String
    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case items
        case nextCursor = "next_cursor"
        case etag
    }
}

struct ResearchTransitionStep: Decodable, Identifiable {
    let stepRef: String
    let edgeRef: String
    let fromNode: String
    let toNode: String
    let createdAt: Double
    let evidenceRefs: [String]
    let trialPlanRefs: [String]
    let runSpecRefs: [String]?
    let obligationRefs: [String]
    let claimRefs: [String]
    let jobRefs: [String]
    let runRefs: [String]
    let deltaRefs: [String]?
    let status: String?
    let objectHrefs: [String]?
    let obligationChanges: [ResearchStateChange]
    let claimChanges: [ResearchStateChange]
    let obligationPresentations: [ResearchObligationPresentation]?
    let evidencePresentations: [ResearchEvidencePresentation]?
    let entryResolution: ResearchEntryResolutionDelta?
    let reportContainer: ResearchTransitionReportContainer?
    var id: String { stepRef }

    enum CodingKeys: String, CodingKey {
        case stepRef = "step_ref"
        case edgeRef = "edge_ref"
        case fromNode = "from_node"
        case toNode = "to_node"
        case createdAt = "created_at"
        case evidenceRefs = "evidence_refs"
        case trialPlanRefs = "trial_plan_refs"
        case runSpecRefs = "run_spec_refs"
        case obligationRefs = "obligation_refs"
        case claimRefs = "claim_refs"
        case jobRefs = "job_refs"
        case runRefs = "run_refs"
        case deltaRefs = "delta_refs"
        case status
        case objectHrefs = "object_hrefs"
        case obligationChanges = "obligation_changes"
        case claimChanges = "claim_changes"
        case obligationPresentations = "obligation_presentations"
        case evidencePresentations = "evidence_presentations"
        case entryResolution = "entry_resolution"
        case reportContainer = "report_container"
    }

    var allRefs: Set<String> {
        Set(
            evidenceRefs + trialPlanRefs + obligationRefs
                + claimRefs + jobRefs + runRefs + (runSpecRefs ?? [])
                + (deltaRefs ?? [])
        )
    }

    func objectHref(kind: String, targetRef: String) -> String? {
        guard let objectID = targetRef.split(
            separator: ":",
            maxSplits: 1
        ).last.map(String.init) else { return nil }
        let expectedPath = "/cycle-objects/\(kind)/\(objectID)"
        return objectHrefs?.first { href in
            guard let components = URLComponents(string: href) else {
                return false
            }
            return components.path.hasSuffix(expectedPath)
        }
    }
}

struct ResearchTransitionReportContainer: Decodable, Equatable {
    let kind: String
    let anchorNode: String
    let episodeRef: String?

    enum CodingKeys: String, CodingKey {
        case kind
        case anchorNode = "anchor_node"
        case episodeRef = "episode_ref"
    }
}

struct ResearchAuditObjectEnvelope: Decodable {
    let object: ResearchAuditObjectPayload
}

struct ResearchAuditObjectPayload: Decodable {
    let schemaVersion: Int
    let title: String?
    let titleZH: String?
    let claimSummary: String?
    let deltaRef: String?
    let traceRef: String?
    let objectKind: String?
    let objectID: String?
    let fromState: String?
    let toState: String?
    let obligationID: String?
    let claimID: String?
    let claimRef: String?
    let obligationKind: String?
    let epistemicQuestion: String?
    let status: String?
    let materiality: String?
    let evidenceState: String?
    let claimType: String?
    let createdEventRef: String?
    let scope: ResearchJSONValue?
    let dischargeCriterion: ResearchJSONValue?
    let requirementRefs: [String]?
    let claimIDs: [String]?
    let evidenceRefs: [String]?
    let trialPlanID: String?
    let trialPlanVersion: Int?
    let hypothesisRef: String?
    let trialFamily: String?
    let protocolRef: String?
    let outcomes: ResearchAuditTrialOutcomes?
    let sampleRoles: [ResearchAuditSampleRole]?
    let evidenceKind: String?
    let envelopeID: String?
    let envelopeHash: String?
    let sourceRefs: [String]?
    let metricRefs: [String]?
    let artifactRefs: [String]?
    let hypothesesTested: Int?
    let stopCondition: String?
    let limitations: [String]?
    let conflicts: [String]?
    let facts: ResearchJSONValue?
    let identityRefs: ResearchJSONValue?
    let runID: String?
    let configurationID: String?
    let configurationRevision: Int?
    let runSpecVersion: Int?
    let runSpecHash: String?
    let runSpecJSON: String?
    let trialRole: String?
    let trialStage: String?
    let comparisonID: String?
    let sampleRef: String?
    let sampleStart: String?
    let sampleEnd: String?
    let aliasZH: String?
    let summaryZH: String?
    let completeParametersJSON: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case title
        case titleZH = "title_zh"
        case claimSummary = "claim_summary"
        case deltaRef = "delta_ref"
        case traceRef = "trace_ref"
        case objectKind = "object_kind"
        case objectID = "object_id"
        case fromState = "from_state"
        case toState = "to_state"
        case obligationID = "obligation_id"
        case claimID = "claim_id"
        case claimRef = "claim_ref"
        case obligationKind = "obligation_kind"
        case epistemicQuestion = "epistemic_question"
        case status
        case materiality
        case evidenceState = "evidence_state"
        case claimType = "claim_type"
        case createdEventRef = "created_event_ref"
        case scope
        case dischargeCriterion = "discharge_criterion"
        case requirementRefs = "requirement_refs"
        case claimIDs = "claim_ids"
        case evidenceRefs = "evidence_refs"
        case trialPlanID = "trial_plan_id"
        case trialPlanVersion = "version"
        case hypothesisRef = "hypothesis_ref"
        case trialFamily = "trial_family"
        case protocolRef = "protocol_ref"
        case outcomes
        case sampleRoles = "sample_roles"
        case evidenceKind = "evidence_kind"
        case envelopeID = "envelope_id"
        case envelopeHash = "envelope_hash"
        case sourceRefs = "source_refs"
        case metricRefs = "metric_refs"
        case artifactRefs = "artifact_refs"
        case hypothesesTested = "hypotheses_tested"
        case stopCondition = "stop_condition"
        case limitations, conflicts
        case facts
        case identityRefs = "identity_refs"
        case runID = "run_id"
        case configurationID = "configuration_id"
        case configurationRevision = "configuration_revision"
        case runSpecVersion = "run_spec_version"
        case runSpecHash = "run_spec_hash"
        case runSpecJSON = "run_spec_json"
        case trialRole = "trial_role"
        case trialStage = "trial_stage"
        case comparisonID = "comparison_id"
        case sampleRef = "sample_ref"
        case sampleStart = "sample_start"
        case sampleEnd = "sample_end"
        case aliasZH = "alias_zh"
        case summaryZH = "summary_zh"
        case completeParametersJSON = "complete_parameters_json"
    }
}

struct ResearchEvidenceDetailEnvelope: Decodable {
    let evidence: ResearchEvidenceDetailPayload
    let access: ResearchCatalogAccess?
}

struct ResearchEvidenceResolvedDetail {
    let evidence: ResearchEvidenceDetailPayload
    let access: ResearchCatalogAccess?
}

struct ResearchEvidenceDetailPayload: Decodable {
    let evidenceRef: String
    let evidenceKind: String
    let envelope: ResearchAuditObjectPayload
    let applicability: ResearchJSONValue
    let fragments: [ResearchEvidenceFragment]
    let tags: [ResearchEvidenceTag]
    let lifecycle: ResearchEvidenceLifecycle
    let createdAt: Double

    enum CodingKeys: String, CodingKey {
        case evidenceRef = "evidence_ref"
        case evidenceKind = "evidence_kind"
        case envelope, applicability, fragments, tags, lifecycle
        case createdAt = "created_at"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        evidenceRef = try values.decode(String.self, forKey: .evidenceRef)
        evidenceKind = try values.decode(String.self, forKey: .evidenceKind)
        envelope = try values.decode(
            ResearchAuditObjectPayload.self, forKey: .envelope
        )
        applicability = try values.decode(
            ResearchJSONValue.self, forKey: .applicability
        )
        fragments = try values.decodeIfPresent(
            [ResearchEvidenceFragment].self, forKey: .fragments
        ) ?? []
        tags = try values.decodeIfPresent(
            [ResearchEvidenceTag].self, forKey: .tags
        ) ?? []
        lifecycle = try values.decodeIfPresent(
            ResearchEvidenceLifecycle.self, forKey: .lifecycle
        ) ?? .active
        createdAt = try values.decode(Double.self, forKey: .createdAt)
    }
}

struct ResearchEvidenceLifecycle: Decodable {
    let status: String
    let latestTransition: ResearchEvidenceLifecycleTransition?

    static let active = ResearchEvidenceLifecycle(
        status: "active", latestTransition: nil
    )

    enum CodingKeys: String, CodingKey {
        case status
        case latestTransition = "latest_transition"
    }
}

struct ResearchEvidenceLifecycleTransition: Decodable {
    let action: String
    let reasonZH: String
    let updatedAt: Double

    enum CodingKeys: String, CodingKey {
        case action
        case reasonZH = "reason_zh"
        case updatedAt = "updated_at"
    }
}

struct ResearchEvidenceFragment: Decodable, Identifiable {
    let fragmentRef: String
    let sourceRef: String
    let selector: ResearchJSONValue
    let fragmentHash: String
    let titleZH: String
    let summaryZH: String
    let preview: ResearchJSONValue
    let source: ResearchEvidenceSource
    var id: String { fragmentRef }

    enum CodingKeys: String, CodingKey {
        case fragmentRef = "fragment_ref"
        case sourceRef = "source_ref"
        case selector
        case fragmentHash = "fragment_hash"
        case titleZH = "title_zh"
        case summaryZH = "summary_zh"
        case preview, source
    }
}

struct ResearchEvidenceSource: Decodable {
    let sourceKind: String
    let identity: ResearchJSONValue
    let contentHash: String
    let audit: ResearchJSONValue
    let capturedAt: Double

    enum CodingKeys: String, CodingKey {
        case sourceKind = "source_kind"
        case identity
        case contentHash = "content_hash"
        case audit
        case capturedAt = "captured_at"
    }
}

struct ResearchEvidenceTag: Decodable, Identifiable {
    let tagRef: String
    let titleZH: String
    let descriptionZH: String
    let status: String
    var id: String { tagRef }

    enum CodingKeys: String, CodingKey {
        case tagRef = "tag_ref"
        case titleZH = "title_zh"
        case descriptionZH = "description_zh"
        case status
    }
}

struct ResearchAuditTrialOutcomes: Decodable {
    let primary: [String]
    let secondary: [String]
}

struct ResearchAuditSampleRole: Decodable, Identifiable {
    let sampleRef: String
    let role: String
    var id: String { "\(sampleRef)|\(role)" }

    enum CodingKeys: String, CodingKey {
        case sampleRef = "sample_ref"
        case role
    }
}

struct ResearchStateChange: Decodable, Identifiable {
    let objectID: String
    let fromState: String
    let toState: String
    let fromRequirementRefs: [String]
    let toRequirementRefs: [String]
    var id: String { "\(objectID):\(fromState):\(toState)" }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(
            keyedBy: DynamicCodingKey.self
        )
        objectID = try values.decodeIfPresent(
            String.self,
            forKey: DynamicCodingKey("obligation_id")
        ) ?? values.decode(
            String.self,
            forKey: DynamicCodingKey("claim_id")
        )
        fromState = try values.decode(
            String.self,
            forKey: DynamicCodingKey("from_state")
        )
        toState = try values.decode(
            String.self,
            forKey: DynamicCodingKey("to_state")
        )
        fromRequirementRefs = try values.decodeIfPresent(
            [String].self,
            forKey: DynamicCodingKey("from_requirement_refs")
        ) ?? []
        toRequirementRefs = try values.decodeIfPresent(
            [String].self,
            forKey: DynamicCodingKey("to_requirement_refs")
        ) ?? []
    }
}

private struct DynamicCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init(_ value: String) { stringValue = value }
    init?(stringValue: String) { self.init(stringValue) }
    init?(intValue: Int) { return nil }
}
