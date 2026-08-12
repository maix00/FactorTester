from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
APPLE = ROOT / "apple"
LOCALIZATIONS = APPLE / "Resources" / "Shared"
CRITICAL_KEYS = {
    "登录",
    "个人中心",
    "界面语言",
    "跟随系统",
    "简体中文",
    "更新密码",
    "初始化来源",
    "可见工作区",
    "新建或更新 Profile",
    "迁移工作区",
    "迁移预览",
    "验证迁移",
    "回滚迁移",
    "版本状态",
    "检查更新",
    "打开上一版 DMG",
    "下载的 DMG 校验失败，未保存也未打开。",
    "尚未配置服务器地址，请先在设置中填写。",
    "此平台不支持本地 Keychain。",
}


def _load(language: str) -> dict[str, str]:
    path = LOCALIZATIONS / "Localizable.xcstrings"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    entries: dict[str, str] = {}
    for key, entry in catalog["strings"].items():
        localization = entry.get("localizations", {}).get(language)
        assert localization, f"{path}: missing {language} translation for {key!r}"
        value = localization["stringUnit"]["value"]
        assert value, f"{path}: empty translation for {key!r}"
        entries[key] = value
    return entries


def test_chinese_and_english_catalogs_have_identical_keys() -> None:
    zh_hans = _load("zh-Hans")
    english = _load("en")
    assert zh_hans.keys() == english.keys()
    assert CRITICAL_KEYS <= zh_hans.keys()


def test_english_critical_ui_is_not_left_as_chinese() -> None:
    english = _load("en")
    for key in CRITICAL_KEYS:
        assert english[key] != key, f"critical English translation missing for {key!r}"


def test_web_literal_translation_keys_are_in_the_shared_catalog() -> None:
    catalog = _load("zh-Hans")
    web_root = ROOT / "server" / "manager" / "web"
    missing: dict[str, list[str]] = {}
    patterns = (
        re.compile(r'''context\.t\(["']([^"']+)["']\)'''),
        re.compile(r'''(?<![A-Za-z])t\(["']([^"']+)["']\)'''),
        re.compile(r'''data-i18n(?:-aria|-placeholder)?=["']([^"']+)["']'''),
    )
    paths = sorted(web_root.glob("*.js")) + sorted(web_root.glob("*.html"))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        keys = set().union(*(pattern.findall(source) for pattern in patterns))
        absent = sorted(keys - catalog.keys())
        if absent:
            missing[path.name] = absent
    assert missing == {}


def test_language_override_is_durable_and_does_not_rewrite_protocol_values() -> None:
    app = (APPLE / "Sources" / "App" / "FactorTesterClientApp.swift").read_text()
    language = (APPLE / "Sources" / "Localization" / "AppLanguage.swift").read_text()
    settings = (
        APPLE / "Sources" / "Features" / "Settings" / "ClientSettingsHub.swift"
    ).read_text()
    assert 'LanguageStore()' in app
    assert 'static let defaultsKey = "client.language"' in language
    assert "UserDefaults" in language
    assert 'static let system = AppLanguage("system")' in language
    assert 'static let simplifiedChinese = AppLanguage("zh-Hans")' in language
    assert 'static let english = AppLanguage("en")' in language
    assert ".environment(" in app and "\\.locale" in app
    assert "JSON、状态值与 API 协议不会随界面语言改变" in settings


def test_localizations_are_bundled_for_both_apple_targets() -> None:
    project = (APPLE / "project.yml").read_text()
    assert project.count("- path: Resources/Shared") == 2
    assert (LOCALIZATIONS / "Localizable.xcstrings").is_file()
