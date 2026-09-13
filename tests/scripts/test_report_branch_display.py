"""Rendered report controls with isolated API/renderer inputs, using real DOM."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('surface', ['embedded', 'dedicated'])
@pytest.mark.parametrize('branch_count', [1, 2])
def test_report_branch_identity_selection_and_content_time(surface, branch_count, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('local Playwright Chromium is unavailable')
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1100, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content('<title>Report branch acceptance</title><header></header><main></main>')
        page.add_script_tag(path=str(ROOT / 'server/manager/web/core/shared-ui.js'))
        page.evaluate('''count => {
          window.branches = [{publication_id:'p-alice', source_kind:'publication', branch_ref:'main',
            principal_ref:'GTHT@Alice@123', profile_ref:'self', selected:true, updated_at:1000},
            {publication_id:'p-bob', source_kind:'publication', branch_ref:'review', principal_ref:'GTHT@Bob@456',
             profile_ref:'self', updated_at:2000}].slice(0, count);
          window.report = {report_id:'shared', title:'Shared report', source_kind:'publication',
            source_ref:'p-alice', owner_ref:'GTHT@ReportOwner@789', profile_ref:'report-owner',
            build_source:'client', visibility:'private', updated_at:100, branches};
          FTUI.iconButton = (_context, _icon, label, action) => {
            const b = document.createElement('button'); b.textContent=label;
            b.addEventListener('click', action); return b;
          };
          window.FTResearchReportSettings = {applyReading() {}};
          window.FTReportSource = {create(id) {return {
            async load() {return {...report, title:id, updated_at:id==='p-bob'?2000:1000};},
            watch(options) {window.publishChange=options.onChange; return () => {};}
          };}};
          window.FTReportRenderer = {render(value, mount) {
            mount.textContent=value.title; return {update(next) {mount.textContent=next.title;}};
          }};
          const session = {};
          window.context = {t:x=>x, state:{}, content:document.querySelector('main'),
            toolbar:document.querySelector('header'), tabSession:()=>session,
            api:async()=>({reports:[report]}), activeNav(){}, setHeading(){},
            updateActiveTab(){}, isRouteCurrent:()=>true, navigate(){}};
        }''', branch_count)
        page.add_script_tag(path=str(ROOT / 'server/manager/web/research/reports.js'))
        page.add_script_tag(path=str(ROOT / 'server/manager/web/report/report-entry.js'))
        if surface == 'embedded':
            page.evaluate('context.tabSession={}; FTResearchReports.renderForResearch(context, context.content, "research")')
        else:
            page.evaluate('FTReportEntry.render("p-alice", context)')
        picker = page.locator('.branch-picker')
        assert picker.locator('option').all_text_contents() == [
            'main · Alice · self', 'review · Bob · self'][:branch_count]
        assert picker.input_value() == 'p-alice'
        assert page.locator('.report-mount').inner_text() == 'p-alice'
        if surface == 'embedded':
            timestamp = page.locator('time.research-report-content-updated')
            assert timestamp.get_attribute('datetime') == '1970-01-01T00:16:40.000Z'
            page.evaluate('publishChange({title:"Updated body", updated_at:3000})')
            assert timestamp.get_attribute('datetime') == '1970-01-01T00:50:00.000Z'
            assert page.locator('.report-mount').inner_text() == 'Updated body'
        if branch_count == 2:
            picker.select_option('p-bob')
            page.wait_for_function('document.querySelector(".report-mount")?.textContent === "p-bob"')
            assert picker.input_value() == 'p-bob'
        assert not errors
        page.screenshot(path=str(tmp_path / f'{surface}-{branch_count}.png'))
        browser.close()
