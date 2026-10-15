"""Quota first paint must not wait for a slow live scan or remote server."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]


def test_quota_renders_saved_snapshot_before_live_inventory() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            page.goto("about:blank")
            page.evaluate("""() => {
              window.FTIcons = {node: () => document.createElement('i')};
              window.FTUI = {
                text: value => String(value),
                actionButton: (label, callback) => {
                  const button = document.createElement('button');
                  button.textContent = label; button.onclick = callback;
                  return button;
                },
                iconButton: (_context, _icon, label, callback) => {
                  const button = document.createElement('button');
                  button.textContent = label; button.onclick = callback;
                  return button;
                },
                refreshButton: (_context, callback) => {
                  const button = document.createElement('button');
                  button.textContent = '刷新'; button.onclick = callback;
                  return button;
                },
                table: (_headers, rows) => {
                  const shell = document.createElement('div');
                  rows.forEach(row => {
                    const line = document.createElement('div');
                    row.forEach(value => line.append(value instanceof Node
                      ? value : document.createTextNode(String(value))));
                    shell.append(line);
                  });
                  return {shell};
                },
              };
              window.quotaRequests = {};
              window.quotaContext = {
                t: value => value,
                session: {username: 'alice'},
                content: document.body,
                activeNav() {}, setHeading() {}, isRouteCurrent: () => true,
                showNotice() {},
                api: path => new Promise((resolve, reject) => {
                  quotaRequests[path] = {resolve, reject};
                }),
              };
            }""")
            page.add_script_tag(path=str(ROOT / "server/manager/web/settings/settings.js"))
            page.evaluate("() => FTSettings.show(quotaContext, 'quota')")
            assert "正在读取配额" in page.locator(".quota-overview").inner_text()
            assert "/api/storage/profile-inventory?snapshot=1" in page.evaluate(
                "Object.keys(quotaRequests)"
            )

            page.evaluate("""() => quotaRequests[
              '/api/storage/profile-inventory?snapshot=1'].resolve({
                quota_bytes: 100,
                job_snapshots: [
                  {storage_server_id: 'local', output_bytes: 70, input_bytes: 20,
                   output_count: 1, input_count: 1, observed_at: '2026-10-15T02:00:00Z'},
                  {storage_server_id: 'remote', output_bytes: 10, input_bytes: 0,
                   output_count: 1, input_count: 0, observed_at: '2026-10-15T01:00:00Z'},
                ],
                profile_snapshots: [{storage_server_id: 'local', inventory: {
                  observed_at: '2026-10-15T02:00:00Z', categories: {
                    research_reports: {bytes: 5, file_count: 1},
                    profile_uploads: {bytes: 0, file_count: 0},
                    profile_workspaces: {bytes: 0, file_count: 0},
                  },
                }}],
                protected_metadata: {factors: {bytes: 0, item_count: 0}},
              })""")
            page.get_by_text("105 B / 100 B", exact=False).wait_for()
            assert "测试任务生成物（历史未分类）" in page.locator(
                ".quota-categories"
            ).inner_text()
            # Neither the live scan nor the remote Job request has resolved.
            assert "/api/storage/profile-inventory" in page.evaluate(
                "Object.keys(quotaRequests)"
            )
            assert "/api/jobs/storage" in page.evaluate("Object.keys(quotaRequests)")

            page.evaluate("""() => quotaRequests['/api/jobs/storage'].resolve({
              storage_server_id: 'local', quota_bytes: 100,
              business_groups: [
                {quota_group: 'output:data', bytes: 70, job_count: 1},
                {quota_group: 'input:other', bytes: 20, job_count: 1},
              ],
              cleanup_preview: {artifact_count: 0},
              servers: [
                {storage_server_id: 'local', output_bytes: 70, input_bytes: 20},
                {storage_server_id: 'remote', output_bytes: 10, input_bytes: 0,
                 output_count: 1, observed_at: '2026-10-15T01:00:00Z'},
              ],
            })""")
            page.get_by_text("测试任务生成物（数据）", exact=False).wait_for()
            assert "105 B / 100 B" in page.locator(".quota-overview").inner_text()
            assert "/api/jobs/storage?server_id=remote" in page.evaluate(
                "Object.keys(quotaRequests)"
            )
            page.evaluate("""() => quotaRequests[
              '/api/jobs/storage?server_id=remote'].resolve({
                storage_server_id: 'remote',
                business_groups: [{quota_group: 'output:image', bytes: 10,
                                   job_count: 1}],
                cleanup_preview: {artifact_count: 0},
              })""")
            page.get_by_text("测试任务生成物（图片）", exact=False).wait_for()
            assert "测试任务生成物（历史未分类）" not in page.locator(
                ".quota-categories"
            ).inner_text()
        finally:
            browser.close()
