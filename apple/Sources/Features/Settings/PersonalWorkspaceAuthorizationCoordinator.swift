import AppKit
import Combine
import Foundation

@MainActor
final class PersonalWorkspaceAuthorizationCoordinator: ObservableObject {
    typealias AuthorizationCheck = @MainActor (URL) -> Bool
    typealias AuthorizationRequest = @MainActor (URL) throws -> Bool

    @Published private(set) var errorMessage: String?

    private let hasAuthorization: AuthorizationCheck
    private let requestAuthorization: AuthorizationRequest
    private var promptedPrincipals: Set<String> = []

    init(
        hasAuthorization: @escaping AuthorizationCheck = {
            PersonalWorkspaceAccessStore.hasAuthorization(for: $0)
        },
        requestAuthorization: @escaping AuthorizationRequest = {
            try PersonalWorkspaceAuthorizationPanel.present(suggestedRoot: $0)
        }
    ) {
        self.hasAuthorization = hasAuthorization
        self.requestAuthorization = requestAuthorization
    }

    func requestIfNeeded(principal: String) {
        guard let root = PersonalWorkspaceAccessStore.expectedRoot(
            for: principal
        ), !hasAuthorization(root),
        promptedPrincipals.insert(principal).inserted else { return }
        do {
            _ = try requestAuthorization(root)
            errorMessage = nil
        } catch {
            errorMessage = L10n.format(
                "无法保存个人工作区授权：%@",
                error.localizedDescription
            )
        }
    }

    func clearError() {
        errorMessage = nil
    }
}

@MainActor
enum PersonalWorkspaceAuthorizationPanel {
    static func present(suggestedRoot: URL) throws -> Bool {
        let panel = NSOpenPanel()
        panel.title = L10n.text("选择 FactorTester 用户目录")
        panel.message = L10n.text(
            "请选择当前用户目录，用于读取本地中文研究报告。"
        )
        panel.prompt = L10n.text("授权读取")
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = suggestedRoot
        guard panel.runModal() == .OK, let url = panel.url else {
            return false
        }
        try PersonalWorkspaceAccessStore.authorize(url)
        return true
    }
}
