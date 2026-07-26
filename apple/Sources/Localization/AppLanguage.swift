import Foundation
import SwiftUI

/// A language identifier backed by the bundled String Catalog.
///
/// This is deliberately not a closed enum: adding a localization in
/// `Localizable.xcstrings` makes the language discoverable without changing
/// view code.
struct AppLanguage: RawRepresentable, Hashable, Identifiable, Sendable {
    let rawValue: String

    init?(rawValue: String) {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        self.rawValue = value
    }

    init(_ rawValue: String) {
        self.rawValue = rawValue
    }

    static let system = AppLanguage("system")
    static let simplifiedChinese = AppLanguage("zh-Hans")
    static let english = AppLanguage("en")

    var id: String { rawValue }

    var locale: Locale {
        self == .system ? .autoupdatingCurrent : Locale(identifier: rawValue)
    }
}

struct LanguageOption: Identifiable, Hashable, Sendable {
    let id: String
    let titleKey: String

    var language: AppLanguage { AppLanguage(id) }
}

enum LanguageCatalog {
    static func options(bundle: Bundle = .main) -> [LanguageOption] {
        let localizedIdentifiers = bundle.localizations
            .filter { $0.caseInsensitiveCompare("Base") != .orderedSame }
            .sorted()
        var result = [LanguageOption(id: AppLanguage.system.rawValue, titleKey: "跟随系统")]
        for identifier in localizedIdentifiers where identifier != AppLanguage.system.rawValue {
            let titleKey: String
            switch identifier {
            case AppLanguage.simplifiedChinese.rawValue:
                titleKey = "简体中文"
            case AppLanguage.english.rawValue:
                titleKey = "English"
            default:
                titleKey = Locale(identifier: identifier)
                    .localizedString(forIdentifier: identifier)
                    ?? identifier
            }
            result.append(LanguageOption(id: identifier, titleKey: titleKey))
        }
        return result
    }
}

@MainActor
final class LanguageStore: ObservableObject {
    nonisolated static let defaultsKey = "client.language"

    @Published var selection: AppLanguage {
        didSet {
            defaults.set(selection.rawValue, forKey: Self.defaultsKey)
        }
    }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let stored = defaults.string(forKey: Self.defaultsKey)
            .flatMap(AppLanguage.init(rawValue:))
        self.selection = stored ?? .system
    }

    var locale: Locale { selection.locale }

    func select(rawValue: String) {
        guard let language = AppLanguage(rawValue: rawValue) else { return }
        selection = language
    }
}

enum L10n {
    static func resource(_ key: String) -> LocalizedStringResource {
        LocalizedStringResource(
            String.LocalizationValue(key),
            table: "Localizable",
            bundle: .main
        )
    }

    static var locale: Locale {
        effectiveLanguage.locale
    }

    static func text(_ key: String) -> String {
        localizedText(key, language: effectiveLanguage)
    }

    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: locale, arguments: arguments)
    }

    static func format(
        _ key: String,
        language: AppLanguage,
        arguments: [CVarArg]
    ) -> String {
        let localized = localizedText(key, language: language)
        return String(
            format: localized,
            locale: language.locale,
            arguments: arguments
        )
    }

    private static func localizedText(
        _ key: String,
        language: AppLanguage
    ) -> String {
        if language == .system {
            return Bundle.main.localizedString(
                forKey: key,
                value: nil,
                table: "Localizable"
            )
        }
        if let resourceURL = Bundle.main.url(
            forResource: language.rawValue,
            withExtension: "lproj"
        ), let localizedBundle = Bundle(url: resourceURL) {
            return localizedBundle.localizedString(
                forKey: key,
                value: key,
                table: "Localizable"
            )
        }
        return Bundle.main.localizedString(
            forKey: key,
            value: key,
            table: "Localizable"
        )
    }

    private static var effectiveLanguage: AppLanguage {
        UserDefaults.standard.string(forKey: LanguageStore.defaultsKey)
            .flatMap(AppLanguage.init(rawValue:)) ?? .system
    }
}
