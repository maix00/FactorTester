#if os(macOS)
import SwiftUI

private struct ResearchDocumentSelectionCoordinatorKey: EnvironmentKey {
    static let defaultValue: ResearchDocumentSelectionCoordinator? = nil
}

extension EnvironmentValues {
    var researchDocumentSelectionCoordinator:
        ResearchDocumentSelectionCoordinator? {
        get { self[ResearchDocumentSelectionCoordinatorKey.self] }
        set { self[ResearchDocumentSelectionCoordinatorKey.self] = newValue }
    }
}
#endif
