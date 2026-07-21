import Foundation

struct ProfileResearchListResponse: Decodable {
    let workspaceRef: String
    let items: [ProfileResearchSummary]
    let nextCursor: String?
    let etag: String

    enum CodingKeys: String, CodingKey {
        case workspaceRef = "workspace_ref"
        case items
        case nextCursor = "next_cursor"
        case etag
    }
}

struct ProfileResearchSummary: Decodable, Identifiable {
    let researchRef: String
    let workPackageRef: String
    let workspaceRef: String
    let productGroup: String
    let status: String
    let branchCount: Int
    let runningBranchCount: Int
    let updatedAt: Double
    let detailHref: String
    let reportLookupRef: String?
    var id: String { researchRef }

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case workPackageRef = "work_package_ref"
        case workspaceRef = "workspace_ref"
        case productGroup = "product_group"
        case status
        case branchCount = "branch_count"
        case runningBranchCount = "running_branch_count"
        case updatedAt = "updated_at"
        case detailHref = "detail_href"
        case reportLookupRef = "report_lookup_ref"
    }
}

struct ProfileResearchWorkPackageDetail: Decodable {
    let researchRef: String
    let workPackageRef: String
    let productGroup: String
    let mode: String
    let branchCount: Int
    let omittedBranchCount: Int
    let branches: [ProfileResearchBranchSummary]
    let reportLookupRef: String?
    let etag: String

    enum CodingKeys: String, CodingKey {
        case researchRef = "research_ref"
        case workPackageRef = "work_package_ref"
        case productGroup = "product_group"
        case mode
        case branchCount = "branch_count"
        case omittedBranchCount = "omitted_branch_count"
        case branches
        case reportLookupRef = "report_lookup_ref"
        case etag
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
    let status: String
    let materiality: String
    let questionSummary: String
    var id: String { obligationRef }
    enum CodingKeys: String, CodingKey {
        case obligationRef = "obligation_ref"
        case status, materiality
        case questionSummary = "question_summary"
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
    let obligationRefs: [String]
    let claimRefs: [String]
    let jobRefs: [String]
    let runRefs: [String]
    let obligationChanges: [ResearchStateChange]
    let claimChanges: [ResearchStateChange]
    var id: String { stepRef }

    enum CodingKeys: String, CodingKey {
        case stepRef = "step_ref"
        case edgeRef = "edge_ref"
        case fromNode = "from_node"
        case toNode = "to_node"
        case createdAt = "created_at"
        case evidenceRefs = "evidence_refs"
        case trialPlanRefs = "trial_plan_refs"
        case obligationRefs = "obligation_refs"
        case claimRefs = "claim_refs"
        case jobRefs = "job_refs"
        case runRefs = "run_refs"
        case obligationChanges = "obligation_changes"
        case claimChanges = "claim_changes"
    }

    var allRefs: Set<String> {
        Set(
            evidenceRefs + trialPlanRefs + obligationRefs
                + claimRefs + jobRefs + runRefs
        )
    }
}

struct ResearchStateChange: Decodable, Identifiable {
    let objectID: String
    let fromState: String
    let toState: String
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
    }
}

private struct DynamicCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init(_ value: String) { stringValue = value }
    init?(stringValue: String) { self.init(stringValue) }
    init?(intValue: Int) { return nil }
}
