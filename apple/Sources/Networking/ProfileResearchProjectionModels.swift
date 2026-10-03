import Foundation

struct ResearchAuditObjectEnvelope: Decodable {
    let object: ResearchAuditObjectPayload
}

struct ResearchAuditObjectPayload: Decodable {
    let schemaVersion: Int
    let title: String?
    let titleZH: String?
    let claimSummary: String?
    let objectKind: String?
    let objectID: String?
    let status: String?
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
        case objectKind = "object_kind"
        case objectID = "object_id"
        case status
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
