from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLE = ROOT / "apple"
LOCALIZATIONS = APPLE / "Resources" / "Shared"
STRINGS_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)";$')

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
    path = LOCALIZATIONS / f"{language}.lproj" / "Localizable.strings"
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("/*"):
            continue
        match = STRINGS_ENTRY.fullmatch(line)
        assert match, f"{path}:{line_number}: malformed strings entry"
        key, value = match.groups()
        assert key not in entries, f"{path}: duplicate key {key!r}"
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


def test_language_override_is_durable_and_does_not_rewrite_protocol_values() -> None:
    app = (APPLE / "Sources" / "App" / "FactorTesterClientApp.swift").read_text()
    language = (APPLE / "Sources" / "Localization" / "AppLanguage.swift").read_text()
    account = (
        APPLE / "Sources" / "Features" / "Account" / "AccountCenterView.swift"
    ).read_text()
    assert '@AppStorage("client.language")' in app
    assert '@AppStorage("client.language")' in account
    assert "case system" in language
    assert 'case simplifiedChinese = "zh-Hans"' in language
    assert 'case english = "en"' in language
    assert ".environment(" in app and "\\.locale" in app
    assert "机器 JSON、状态值与 API 协议保持不变" in account


def test_localizations_are_bundled_for_both_apple_targets() -> None:
    project = (APPLE / "project.yml").read_text()
    assert project.count("- path: Resources/Shared") == 2
    assert (LOCALIZATIONS / "zh-Hans.lproj" / "Localizable.strings").is_file()
    assert (LOCALIZATIONS / "en.lproj" / "Localizable.strings").is_file()
