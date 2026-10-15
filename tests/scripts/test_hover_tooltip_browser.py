"""The shared hover hint matches the Agent drawer's compact black bubble."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "server" / "manager" / "web"


def test_hover_tooltips_replace_native_titles_without_restyling_rich_previews() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 400, "height": 300})
        try:
            page.set_content("""
              <button id="titled" title="设置" style="margin: 30px">设置图标</button>
              <button id="icon" class="icon-action-button" title="刷新" aria-label="刷新"
                style="position: fixed; right: 0; bottom: 0">↻</button>
              <button id="labelled" title="提交当前配置">提交</button>
              <button id="aria-only" aria-label="不显示新增提示">仅有无障碍名称</button>
              <div class="chapter-rail-tooltip" role="tooltip" title="预览">预览</div>
              <div class="ft-help-bubble" hidden>帮助说明</div>
            """)
            page.add_style_tag(path=str(WEB / "styles" / "app.css"))
            page.add_style_tag(path=str(WEB / "styles" / "report.css"))
            page.add_script_tag(path=str(WEB / "core" / "hover-tooltip.js"))
            hint = page.locator("#ft-hover-tooltip")

            page.locator("#titled").hover()
            page.wait_for_timeout(260)
            assert hint.is_visible()
            assert hint.inner_text() == "设置"
            assert hint.evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(21, 21, 21)"
            assert page.locator("#titled").get_attribute("title") is None
            assert hint.get_attribute("data-placement") == "below"

            page.locator("#titled").evaluate("node => { node.title = '新的设置'; }")
            assert hint.inner_text() == "新的设置"
            page.locator("#icon").hover()
            page.wait_for_timeout(260)
            assert hint.inner_text() == "刷新"
            assert hint.get_attribute("data-placement") == "above"
            assert page.locator("#titled").get_attribute("title") == "新的设置"

            page.mouse.click(200, 200)
            assert hint.is_hidden()
            page.locator("#labelled").hover()
            page.wait_for_timeout(260)
            assert hint.inner_text() == "提交当前配置"
            page.locator("#aria-only").hover()
            page.wait_for_timeout(260)
            assert hint.is_hidden()
            page.locator("#titled").focus()
            assert hint.is_visible()
            assert hint.inner_text() == "新的设置"
            page.keyboard.press("Escape")
            assert hint.is_hidden()
            page.locator(".chapter-rail-tooltip").evaluate(
                "node => node.dispatchEvent(new PointerEvent('pointerover', {bubbles: true}))"
            )
            assert hint.is_hidden()
            assert page.locator(".chapter-rail-tooltip").evaluate(
                "node => getComputedStyle(node).backgroundColor"
            ) != "rgb(21, 21, 21)"
            assert page.locator(".ft-help-bubble").evaluate(
                "node => getComputedStyle(node).backgroundColor"
            ) != "rgb(21, 21, 21)"
        finally:
            browser.close()
