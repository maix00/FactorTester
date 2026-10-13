"""The report's embedded Job panel must stay inside its own timeline level."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("viewport_width", [900, 500])
def test_nested_report_job_panel_uses_section_width(viewport_width):
    playwright = pytest.importorskip("playwright.sync_api")
    css = (Path(__file__).parents[2] / "server/manager/web/styles/report.css").read_text()
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(channel="chrome", headless=True)
        except Exception as error:
            pytest.skip(f"Chrome browser unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": viewport_width, "height": 700})
            page.set_content(f"""
                <style>{css}</style>
                <div class="report-mount" style="width:min(800px, 100%)">
                  <article class="chapter">
                    <div class="section-bridge contains-section-bridge">
                      <section class="component section bridge-entry depth-0">
                        <details open><summary>第一层</summary>
                          <div class="component-children">
                            <div class="section-bridge contains-section-bridge">
                              <section class="component section bridge-entry depth-1">
                                <details open><summary>第二层</summary>
                                  <div class="component-children">
                                    <div class="section-bridge contains-section-bridge">
                                      <section class="component special test_result bridge-entry depth-2">
                                        <details open><summary>回测运行结果</summary>
                                          <div class="report-job-result">
                                            <div class="test-run-inline-results">
                                              <div>任务进度</div>
                                              <table style="min-width:1200px"><tr><td>宽表格</td></tr></table>
                                            </div>
                                          </div>
                                        </details>
                                      </section>
                                    </div>
                                  </div>
                                </details>
                              </section>
                            </div>
                          </div>
                        </details>
                      </section>
                    </div>
                  </article>
                </div>
            """)
            geometry = page.evaluate("""() => {
              const section = document.querySelector('.component.test_result');
              const panel = section.querySelector('.report-job-result');
              const parent = section.querySelector('details');
              const rect = node => node.getBoundingClientRect();
              return {
                sectionLeft: rect(section).left,
                panelLeft: rect(panel).left,
                panelRight: rect(panel).right,
                parentRight: rect(parent).right,
                horizontalOverflow: panel.scrollWidth > panel.clientWidth,
              };
            }""")
            assert geometry["panelLeft"] - geometry["sectionLeft"] == pytest.approx(20)
            assert geometry["panelRight"] <= geometry["parentRight"] + 1
            assert geometry["horizontalOverflow"]
        finally:
            browser.close()
