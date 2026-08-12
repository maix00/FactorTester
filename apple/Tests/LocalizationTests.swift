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

    func testFormatUsesTheSelectedLanguageCatalog() {
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .english,
                arguments: ["0.1.3-beta.32"]
            ),
            "Current version 0.1.3-beta.32"
        )
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .simplifiedChinese,
                arguments: ["0.1.3-beta.32"]
            ),
            "当前版本 0.1.3-beta.32"
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

    init(language: AppLanguage) { self.language = language }

    func read(principal: String) async throws -> AppLanguage { language }

    func update(language: AppLanguage, principal: String) async throws {
        self.language = language
    }

    func currentLanguage() -> AppLanguage { language }
}
