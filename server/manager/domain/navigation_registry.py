"""Authoritative Manager navigation registry and access filtering."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_RESEARCH_TABS = (
    {
        "id": "research.evidence",
        "title": "证据",
        "title_key": "证据",
        "description_key": "浏览本人登记的本地与服务器研究证据",
        "sfSymbol": "doc.text.magnifyingglass",
        "path": "/research?section=evidence",
        "requiresAuth": True,
        "roles": [],
    },
    {
        "id": "research.reports",
        "title": "研究报告",
        "title_key": "研究报告",
        "description_key": "浏览本人、下级用户和公开共享的研究报告",
        "sfSymbol": "doc.text",
        "path": "/research?section=reports",
        "requiresAuth": True,
        "roles": [],
    },
    {
        "id": "research.graph",
        "title": "研究图",
        "title_key": "研究图",
        "description_key": "浏览研究图与研究周期",
        "sfSymbol": "point.3.connected.trianglepath.dotted",
        "path": "/research?section=graph",
        "requiresAuth": True,
        "roles": [],
    },
    {
        "id": "research.profiles",
        "title": "研究身份",
        "title_key": "研究身份",
        "description_key": "查看研究身份、工作区与初始化来源",
        "sfSymbol": "person.2.crop.square.stack",
        "path": "/research?section=profiles",
        "requiresAuth": True,
        "roles": [],
    },
    {
        "id": "research.agent-models",
        "title": "智能体模型",
        "title_key": "智能体模型",
        "description_key": "管理客户端或服务器 Agent 使用的模型服务",
        "sfSymbol": "server.rack",
        "path": "/research?section=agent-models",
        "requiresAuth": True,
        "roles": [],
    },
)

_TEST_TYPE_MODULES = (
    {
        "id": "factor-series", "title": "查看因子序列", "title_key": "查看因子序列",
        "desc": "计算并查看因子值、价格与合约区间",
        "description_key": "计算并查看因子值、价格与合约区间",
        "icon": "FS", "sfSymbol": "waveform.path.ecg", "path": "/factor-series",
        "requiresAuth": False, "roles": [], "sidebarVisible": False,
        "homeVisible": False, "pinned": False, "tab_behavior": "new",
    },
    {
        "id": "ic-test",
        "title": "IC 测试",
        "title_key": "IC 测试",
        "desc": "配置并运行因子 IC 测试",
        "description_key": "配置并运行因子 IC 测试",
        "icon": "IC",
        "sfSymbol": "chart.xyaxis.line",
        "path": "/ic-test",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
        "tab_behavior": "new",
    },
    {
        "id": "backtest",
        "title": "回测",
        "title_key": "回测",
        "desc": "配置并运行分组回测",
        "description_key": "配置并运行分组回测",
        "icon": "BT",
        "sfSymbol": "chart.line.uptrend.xyaxis",
        "path": "/backtest",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
        "tab_behavior": "new",
    },
)

_TEST_TABS = (
    {
        "id": "jobs.types",
        "title": "测试类型",
        "title_key": "测试类型",
        "description_key": "选择要运行的测试类型",
        "path": "/jobs?section=types",
        "requiresAuth": False,
        "roles": [],
        "children": list(_TEST_TYPE_MODULES),
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
    },
    {
        "id": "jobs.list",
        "title": "测试任务",
        "title_key": "测试任务",
        "description_key": "查看测试任务、进度、结果与生成物",
        "path": "/jobs?section=tasks",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
    },
)


# This is the only top-level client navigation list.  Server-side access
# filtering below runs before this value is returned to Web or Swift.
_NAVIGATION_MODULES: tuple[dict[str, Any], ...] = (
    {
        "id": "home",
        "title": "主页",
        "title_key": "主页",
        "desc": "选择研究模块",
        "icon": "grid",
        "sfSymbol": "square.grid.2x2",
        "path": "/",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": True,
        "homeVisible": False,
        "pinned": True,
    },
    {
        "id": "research",
        "title": "研究台",
        "title_key": "研究台",
        "desc": "研究报告、研究图与研究身份",
        "description_key": "查看各 Profile 的实时步骤、义务与报告",
        "icon": "research",
        "sfSymbol": "lightbulb",
        "path": "/research?section=researches",
        "requiresAuth": True,
        "roles": [],
        "children": list(_RESEARCH_TABS),
        "sidebarVisible": True,
        "homeVisible": True,
        "pinned": True,
    },
    {
        "id": "factor-series", "title": "查看因子序列", "title_key": "查看因子序列",
        "desc": "计算并查看因子值、价格与合约区间",
        "description_key": "计算并查看因子值、价格与合约区间",
        "icon": "FS", "sfSymbol": "waveform.path.ecg", "path": "/factor-series",
        "requiresAuth": False, "roles": [], "sidebarVisible": False,
        "homeVisible": False, "pinned": False, "tab_behavior": "new",
    },
    {
        "id": "ic-test",
        "title": "IC 测试",
        "title_key": "IC 测试",
        "desc": "配置并运行因子 IC 测试",
        "description_key": "配置并运行因子 IC 测试",
        "icon": "IC",
        "sfSymbol": "chart.xyaxis.line",
        "path": "/ic-test",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
        "tab_behavior": "new",
    },
    {
        "id": "backtest",
        "title": "回测",
        "title_key": "回测",
        "desc": "配置并运行分组回测",
        "description_key": "配置并运行分组回测",
        "icon": "BT",
        "sfSymbol": "chart.line.uptrend.xyaxis",
        "path": "/backtest",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": False,
        "tab_behavior": "new",
    },
    {
        "id": "jobs",
        "title": "测试台",
        "title_key": "测试台",
        "desc": "选择测试类型或查看测试任务",
        "description_key": "选择测试类型或查看测试任务",
        "icon": "任务",
        "sfSymbol": "checklist",
        "path": "/jobs?section=types",
        "requiresAuth": False,
        "roles": [],
        "children": list(_TEST_TABS),
        "sidebarVisible": True,
        "homeVisible": True,
        "pinned": True,
    },
    {
        "id": "factors",
        "title": "因子库",
        "title_key": "因子库",
        "desc": "浏览公共与个人因子",
        "description_key": "浏览 canonical 与自定义因子",
        "icon": "function",
        "sfSymbol": "function",
        "path": "/factors",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": True,
        "homeVisible": True,
        "pinned": True,
    },
    {
        "id": "products",
        "title": "产品库",
        "title_key": "产品库",
        "desc": "查询产品、合约与市场资料",
        "description_key": "查询产品、合约与市场资料",
        "icon": "box",
        "sfSymbol": "shippingbox",
        "path": "/products",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": True,
        "homeVisible": True,
        "pinned": True,
    },
    {
        "id": "manager",
        "title": "服务器管理",
        "title_key": "服务器管理",
        "desc": "查看端口状态并控制本机服务",
        "description_key": "查看端口状态并控制本机服务",
        "icon": "server",
        "sfSymbol": "server.rack",
        "path": "/manager",
        "requiresAuth": True,
        "roles": ["super_admin"],
        "sidebarVisible": False,
        "homeVisible": True,
        "pinned": False,
        "tab_behavior": "new",
        "capabilities": ["server.manage"],
    },
    {
        "id": "mihomo",
        "title": "Mihomo Dashboard",
        "title_key": "Mihomo Dashboard",
        "desc": "打开官方 Mihomo Dashboard",
        "description_key": "打开官方 Mihomo Dashboard",
        "icon": "server",
        "sfSymbol": "network",
        "path": "/mihomo",
        "requiresAuth": True,
        "roles": ["super_admin"],
        "sidebarVisible": False,
        "homeVisible": True,
        "pinned": False,
        "tab_behavior": "new",
        "capabilities": ["server.manage"],
    },
    {
        "id": "sqlite_web",
        "title": "数据库",
        "title_key": "数据库",
        "desc": "浏览统一 SQLite 数据库",
        "description_key": "浏览统一 SQLite 数据库",
        "icon": "SQL",
        "sfSymbol": "cylinder.split.1x2",
        "path": "/sqlite-web/",
        "requiresAuth": True,
        "roles": ["super_admin"],
        "sidebarVisible": False,
        "homeVisible": True,
        "pinned": False,
        "tab_behavior": "new",
        "capabilities": ["database.read"],
    },
    {
        "id": "docs",
        "title": "技术文档",
        "title_key": "技术文档",
        "desc": "阅读 FactorTester 技术文档",
        "description_key": "阅读 FactorTester 技术文档",
        "icon": "📖",
        "sfSymbol": "book",
        "path": "/docs",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": True,
        "pinned": False,
        "tab_behavior": "new",
    },
    {
        "id": "settings",
        "title": "设置",
        "title_key": "设置",
        "desc": "账户与客户端设置",
        "description_key": "账户与客户端设置",
        "icon": "settings",
        "sfSymbol": "person.crop.circle",
        "path": "/settings/account",
        "requiresAuth": False,
        "roles": [],
        "sidebarVisible": False,
        "homeVisible": False,
        "pinned": True,
    },
)


def navigation_modules(session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return only modules allowed for the current Manager session."""
    role = str((session or {}).get("role") or "")
    authenticated = session is not None
    capabilities = {
        str(key)
        for key, enabled in dict((session or {}).get("capabilities") or {}).items()
        if enabled
    }
    if role == "super_admin":
        capabilities.update({"server.manage", "user.manage", "database.read"})
    return [
        _visible_copy(item, role, capabilities, authenticated)
        for item in _NAVIGATION_MODULES
        if _allowed(item, role, capabilities, authenticated)
    ]


def _allowed(
    item: Mapping[str, Any], role: str, capabilities: set[str], authenticated: bool,
) -> bool:
    if bool(item.get("requiresAuth", True)) and not authenticated:
        return False
    roles = {str(value) for value in item.get("roles") or []}
    required = {str(value) for value in item.get("capabilities") or []}
    return (not roles or role in roles) and (not required or required <= capabilities)


def _visible_copy(
    item: Mapping[str, Any], role: str, capabilities: set[str], authenticated: bool,
) -> dict[str, Any]:
    value = deepcopy(dict(item))
    value.pop("capabilities", None)
    children = value.get("children")
    if isinstance(children, list):
        value["children"] = [
            _visible_copy(child, role, capabilities, authenticated)
            for child in children
            if isinstance(child, Mapping)
            and _allowed(child, role, capabilities, authenticated)
        ]
    return value
