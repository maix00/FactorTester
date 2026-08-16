import Foundation
import XCTest
@testable import FTClient

class SimplifiedChineseLocalizedTestCase: XCTestCase {
    private var previousLanguageValue: Any?

    override func setUp() {
        super.setUp()
        let defaults = UserDefaults.standard
        previousLanguageValue = defaults.object(
            forKey: LanguageStore.defaultsKey
        )
        defaults.set(
            AppLanguage.simplifiedChinese.rawValue,
            forKey: LanguageStore.defaultsKey
        )
    }

    override func tearDown() {
        let defaults = UserDefaults.standard
        if let previousLanguageValue {
            defaults.set(
                previousLanguageValue,
                forKey: LanguageStore.defaultsKey
            )
        } else {
            defaults.removeObject(forKey: LanguageStore.defaultsKey)
        }
        previousLanguageValue = nil
        super.tearDown()
    }
}

@MainActor
final class LocalizationTests: XCTestCase {
    func testBundledCatalogExposesSupportedLanguages() {
        let ids = Set(LanguageCatalog.options().map(\.id))

        XCTAssertTrue(ids.contains(AppLanguage.system.rawValue))
        XCTAssertTrue(ids.contains(AppLanguage.english.rawValue))
        XCTAssertTrue(ids.contains(AppLanguage.simplifiedChinese.rawValue))
    }

    func testLanguageIdentifierAcceptsFutureCatalogs() {
        let future = AppLanguage("pt-BR")

        XCTAssertEqual(future.rawValue, "pt-BR")
        XCTAssertTrue(["pt-BR", "pt_BR"].contains(future.locale.identifier))
        XCTAssertNotEqual(future, .system)
    }

    func testLanguageStoreScopesSelectionToTheSignedInUser() async {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let preferences = LanguagePreferenceStub(language: .english)

        let store = LanguageStore(
            defaults: defaults,
            preferences: preferences
        )
        XCTAssertEqual(store.selection, .system)

        await store.synchronize(principal: "alice")
        XCTAssertEqual(store.selection, .english)

        store.select(rawValue: AppLanguage.simplifiedChinese.rawValue)
        try? await Task.sleep(nanoseconds: 20_000_000)
        let persistedLanguage = await preferences.currentLanguage()
        XCTAssertEqual(persistedLanguage, .simplifiedChinese)

        await store.synchronize(principal: nil)
        XCTAssertEqual(store.selection, .simplifiedChinese)
    }

    func testLanguageStorePreservesLastSelectionAcrossAppRestart() {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set(
            AppLanguage.simplifiedChinese.rawValue,
            forKey: LanguageStore.defaultsKey
        )

        let store = LanguageStore(
            defaults: defaults,
            preferences: LanguagePreferenceStub(language: .english)
        )

        XCTAssertEqual(store.selection, .simplifiedChinese)
        XCTAssertEqual(
            defaults.string(forKey: LanguageStore.defaultsKey),
            AppLanguage.simplifiedChinese.rawValue
        )
    }

    func testLanguageStoreMigratesOwnerScopedPreferenceWhenRemoteIsUnconfigured() async {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set(
            AppLanguage.simplifiedChinese.rawValue,
            forKey: "\(LanguageStore.defaultsKey).user.alice"
        )
        let preferences = LanguagePreferenceStub(
            language: .system,
            configured: false
        )
        let store = LanguageStore(
            defaults: defaults,
            preferences: preferences
        )

        await store.synchronize(principal: "alice")

        let persistedLanguage = await preferences.currentLanguage()
        let configured = await preferences.isConfigured()
        XCTAssertEqual(store.selection, .simplifiedChinese)
        XCTAssertEqual(persistedLanguage, .simplifiedChinese)
        XCTAssertTrue(configured)
    }

    func testLanguageStoreDoesNotMigrateAnotherUsersLastSelection() async {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set(
            AppLanguage.simplifiedChinese.rawValue,
            forKey: LanguageStore.defaultsKey
        )
        let preferences = LanguagePreferenceStub(
            language: .system,
            configured: false
        )
        let store = LanguageStore(
            defaults: defaults,
            preferences: preferences
        )

        await store.synchronize(principal: "bob")

        let configured = await preferences.isConfigured()
        XCTAssertEqual(store.selection, .system)
        XCTAssertFalse(configured)
    }

    func testExplicitRemoteSystemPreferenceRemainsAuthoritative() async {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        defaults.set(
            AppLanguage.simplifiedChinese.rawValue,
            forKey: "\(LanguageStore.defaultsKey).user.alice"
        )
        let preferences = LanguagePreferenceStub(
            language: .system,
            configured: true
        )
        let store = LanguageStore(
            defaults: defaults,
            preferences: preferences
        )

        await store.synchronize(principal: "alice")

        let configured = await preferences.isConfigured()
        XCTAssertEqual(store.selection, .system)
        XCTAssertTrue(configured)
    }

    func testFormatUsesTheSelectedLanguageCatalog() {
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .english,
                arguments: ["0.1.3-dev"]
            ),
            "Current version 0.1.3-dev"
        )
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .simplifiedChinese,
                arguments: ["0.1.3-dev"]
            ),
            "当前版本 0.1.3-dev"
        )
    }

    func testExplicitTextUsesTheLanguageStoreSelection() {
        XCTAssertEqual(
            L10n.text("功能入口", language: .english),
            "Features"
        )
        XCTAssertEqual(
            L10n.text("功能入口", language: .simplifiedChinese),
            "功能入口"
        )
    }

}

private actor LanguagePreferenceStub: UserLanguagePreferenceAPI {
    private var language: AppLanguage
    private var configured: Bool

    init(language: AppLanguage, configured: Bool = true) {
        self.language = language
        self.configured = configured
    }

    func read(principal: String) async throws -> UserLanguagePreference {
        UserLanguagePreference(language: language, configured: configured)
    }

    func update(language: AppLanguage, principal: String) async throws {
        self.language = language
        configured = true
    }

    func currentLanguage() -> AppLanguage { language }
    func isConfigured() -> Bool { configured }
}
