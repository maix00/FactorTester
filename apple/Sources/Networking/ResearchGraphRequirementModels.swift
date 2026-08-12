import Foundation

struct ResearchGraphRequirementCatalog: Decodable {
    let revision: Int
    let categories: [ResearchGraphRequirementCategory]
    let requirements: [ResearchGraphRequirementDescriptor]

    init(
        revision: Int = 0,
        categories: [ResearchGraphRequirementCategory] = [],
        requirements: [ResearchGraphRequirementDescriptor] = []
    ) {
        self.revision = revision
        self.categories = categories
        self.requirements = requirements
    }

    enum CodingKeys: String, CodingKey {
        case revision = "catalog_revision"
        case categories
        case requirements
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        revision = try values.decodeIfPresent(Int.self, forKey: .revision) ?? 0
        categories = try values.decodeIfPresent(
            [ResearchGraphRequirementCategory].self,
            forKey: .categories
        ) ?? []
        requirements = try values.decodeIfPresent(
            [ResearchGraphRequirementDescriptor].self,
            forKey: .requirements
        ) ?? []
    }
}

struct ResearchGraphRequirementCategory: Decodable, Identifiable {
    let id: String
    let titleZh: String
    let descriptionZh: String

    enum CodingKeys: String, CodingKey {
        case id = "category_id"
        case titleZh = "title_zh"
        case descriptionZh = "description_zh"
    }
}

struct ResearchGraphRequirementDescriptor: Decodable, Identifiable {
    let id: String
    let categoryID: String
    let revision: Int
    let titleZh: String
    let questionZh: String
    let selectWhenZh: String
    let evidenceExpectedZh: [String]
    let notSufficientZh: [String]

    enum CodingKeys: String, CodingKey {
        case id = "requirement_id"
        case categoryID = "category_id"
        case revision
        case titleZh = "title_zh"
        case questionZh = "question_zh"
        case selectWhenZh = "select_when_zh"
        case evidenceExpectedZh = "evidence_expected_zh"
        case notSufficientZh = "not_sufficient_zh"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        categoryID = try values.decode(String.self, forKey: .categoryID)
        revision = try values.decodeIfPresent(Int.self, forKey: .revision) ?? 0
        titleZh = try values.decodeIfPresent(
            String.self,
            forKey: .titleZh
        ) ?? id
        questionZh = try values.decodeIfPresent(
            String.self,
            forKey: .questionZh
        ) ?? ""
        selectWhenZh = try values.decodeIfPresent(
            String.self,
            forKey: .selectWhenZh
        ) ?? ""
        evidenceExpectedZh = try values.decodeIfPresent(
            [String].self,
            forKey: .evidenceExpectedZh
        ) ?? []
        notSufficientZh = try values.decodeIfPresent(
            [String].self,
            forKey: .notSufficientZh
        ) ?? []
    }
}

struct ResearchGraphRequirement: Identifiable, Equatable {
    let id: String
    let categoryID: String
    let categoryTitle: String
    let revision: Int
    let title: String
    let question: String
    let selectWhen: String
    let expectedEvidence: [String]
    let notSufficient: [String]

    init(
        descriptor: ResearchGraphRequirementDescriptor,
        categoryTitle: String
    ) {
        id = descriptor.id
        categoryID = descriptor.categoryID
        self.categoryTitle = categoryTitle
        revision = descriptor.revision
        title = descriptor.titleZh
        question = descriptor.questionZh
        selectWhen = descriptor.selectWhenZh
        expectedEvidence = descriptor.evidenceExpectedZh
        notSufficient = descriptor.notSufficientZh
    }
}
