import XCTest
@testable import FTClient

final class ResearchDocumentReferenceRoutingTests: XCTestCase {
    func testReferenceLocationSelectsOnlySameComponentBinding() {
        let first = binding(componentID: "entry-1", port: "8141")
        let second = binding(componentID: "entry-2", port: "8142")
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "job:shared",
            label: "第二个任务",
            componentID: "entry-2"
        )

        XCTAssertEqual(
            ResearchDocumentReferenceBindingResolver.binding(
                for: reference,
                in: [first, second]
            )?.componentID,
            "entry-2"
        )
        XCTAssertNil(
            ResearchDocumentReferenceBindingResolver.binding(
                for: .init(
                    kind: "job",
                    targetRef: "job:shared",
                    label: "无位置"
                ),
                in: [first, second]
            )
        )
    }

    func testJobRouteRequiresValidatedBindingPort() {
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "job:shared",
            label: "任务",
            componentID: "entry-2"
        )
        XCTAssertEqual(
            ResearchDocumentReferenceBindingResolver.jobRoute(
                for: reference,
                binding: binding(componentID: "entry-2", port: "8142")
            ),
            .init(jobID: "shared", port: 8142)
        )
        XCTAssertNil(
            ResearchDocumentReferenceBindingResolver.jobRoute(
                for: reference,
                binding: binding(componentID: "entry-2", port: "")
            )
        )
    }

    func testProfileRouteUsesOnlyExplicitProfileReference() {
        let reference = ResearchDocumentTypedLink(
            kind: "profile",
            targetRef: "profile:maxa",
            label: "MaxA"
        )
        XCTAssertEqual(
            ResearchDocumentReferenceBindingResolver.profileID(
                for: reference,
                binding: .init(
                    id: "profile-binding",
                    componentID: "entry",
                    kind: "profile",
                    targetRef: "profile:maxa",
                    label: "MaxA",
                    detailFields: []
                )
            ),
            "maxa"
        )
        XCTAssertNil(
            ResearchDocumentReferenceBindingResolver.profileID(
                for: reference,
                binding: nil
            )
        )
        XCTAssertNil(ResearchDocumentReferenceRouter.profileID(from: .init(
            kind: "profile_revision",
            targetRef: "profile-revision:v1:maxa:sha256:abc",
            label: "MaxA 版本"
        )))
    }

    func testJobTabsAreScopedByPort() {
        let base = TestJob(
            id: "same-id",
            kind: "test",
            status: "succeeded",
            workspaceID: "",
            port: 8141,
            profile: "",
            updatedAt: nil,
            artifactCount: 0
        )
        let other = TestJob(
            id: base.id,
            kind: base.kind,
            status: base.status,
            workspaceID: "",
            port: 8142,
            profile: "",
            updatedAt: nil,
            artifactCount: 0
        )
        XCTAssertNotEqual(
            ClientTab.testJob(base).id,
            ClientTab.testJob(other).id
        )
    }

    private func binding(
        componentID: String,
        port: String
    ) -> ResearchDocumentBinding {
        .init(
            id: "binding-\(componentID)",
            componentID: componentID,
            kind: "job",
            targetRef: "job:shared",
            label: "任务",
            detailFields: port.isEmpty
                ? []
                : [.init(name: "port", value: port)]
        )
    }
}
