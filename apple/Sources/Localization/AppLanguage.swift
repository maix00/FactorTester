import Foundation

enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case simplifiedChinese = "zh-Hans"
    case english = "en"

    var id: String { rawValue }

    var locale: Locale {
        self == .system ? .autoupdatingCurrent : Locale(identifier: rawValue)
    }
}

enum L10n {
    static func text(_ key: String) -> String {
        let language = UserDefaults.standard.string(forKey: "client.language")
            .flatMap(AppLanguage.init(rawValue:)) ?? .system
        guard language != .system,
              let path = Bundle.main.path(
                forResource: language.rawValue,
                ofType: "lproj"
              ),
              let bundle = Bundle(path: path) else {
            return NSLocalizedString(key, comment: "")
        }
        return bundle.localizedString(forKey: key, value: nil, table: nil)
    }
}
