#!/usr/bin/env python3
"""Isolated browser → Manager → Keycloak smoke; no existing users or data touched.

Uses the installed GTHT environment, local npm dependencies and a pre-existing
Keycloak image. Profile membership is a denial-only test double. Server-side
creation exercised here is a transition path, not a local-first workflow.
"""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

from playwright.sync_api import sync_playwright

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from scripts.test.keycloak_research_grant_smoke import NoProfileGrants
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import ensure_keycloak_resource
from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
from server.identity.keycloak_research import (
    KeycloakResearchAuthorization,
    KeycloakResearchGrantManager,
)
from server.identity.request_context import bind_verified_identity, identity_request
from server.manager import runtime as manager
from server.manager.services.client_state import ClientStateService
from server.manager.services.research_catalog import ResearchCatalog

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "web/app"


def run(sandbox, bundle, stylesheet):
    realm, client_id = "browser-sharing", "browser-client"
    secret, password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    sandbox.request(
        "POST",
        "/admin/realms",
        token=sandbox.admin,
        body={
            "realm": realm,
            "enabled": True,
            "sslRequired": "none",
            "registrationAllowed": False,
        },
    )
    profile = sandbox.api("GET", realm, "users/profile")
    profile["attributes"].append(
        {
            "name": "tr_identity_id",
            "displayName": "Stable ID",
            "permissions": {"view": ["admin"], "edit": ["admin"]},
        }
    )
    sandbox.api("PUT", realm, "users/profile", profile)
    sandbox.api(
        "POST",
        realm,
        "clients",
        {
            "clientId": client_id,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "secret": secret,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": True,
            "authorizationServicesEnabled": True,
        },
    )
    cid = sandbox.find(
        realm,
        "clients?" + urlencode({"clientId": client_id}),
        client_id,
        field="clientId",
    )["id"]
    for mapper in [
        {
            "name": "stable-id",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "user.attribute": "tr_identity_id",
                "claim.name": "tr_identity_id",
                "jsonType.label": "String",
                "access.token.claim": "true",
                "introspection.token.claim": "true",
            },
        },
        {
            "name": "audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.client.audience": client_id,
                "access.token.claim": "true",
            },
        },
    ]:
        sandbox.api(
            "POST", realm, "clients/" + cid + "/protocol-mappers/models", mapper
        )
    for role in ["public_server:login", "agent_assistant:use"]:
        sandbox.api("POST", realm, "clients/" + cid + "/roles", {"name": role})
    for name in ["owner", "member", "late"]:
        sandbox.api(
            "POST",
            realm,
            "users",
            {
                "username": name,
                "enabled": True,
                "emailVerified": True,
                "firstName": "Temporary",
                "lastName": "User",
                "email": name + "@example.invalid",
                "attributes": {"tr_identity_id": ["stable-" + name]},
                "credentials": [
                    {"type": "password", "value": password, "temporary": False}
                ],
            },
        )
    users = {
        name: sandbox.find(
            realm,
            "users?" + urlencode({"username": name, "exact": "true"}),
            name,
            field="username",
        )
        for name in ["owner", "member", "late"]
    }
    for role in ["public_server:login", "agent_assistant:use"]:
        value = sandbox.api(
            "GET", realm, "clients/" + cid + "/roles/" + quote(role, safe="")
        )

        for account in users.values():
            sandbox.api(
                "POST",
                realm,
                "users/" + account["id"] + "/role-mappings/clients/" + cid,
                [value],
            )
    client = ServiceOIDCClient(sandbox.base, realm, client_id, client_secret=secret)
    issuer = "http://localhost:8080/realms/" + realm
    sessions = {}
    for name, row in users.items():
        token = client._token(
            {
                "grant_type": "password",
                "client_id": client_id,
                "username": name,
                "password": password,
            }
        )["access_token"]
        claims = client.introspect(token)
        assert (
            claims.get("active") is True
            and claims.get("iss") == issuer
            and claims.get("tr_identity_id") == "stable-" + name
        )
        sessions[name] = (
            token,
            {
                "username": name,
                "keycloak_issuer": issuer,
                "keycloak_subject": row["id"],
                "tr_identity_id": "stable-" + name,
            },
        )
    settings = {
        "issuer": issuer,
        "audience": client_id,
        "roles_client_id": client_id,
        "client_id": client_id,
        "backchannel_base_url": sandbox.base,
        "base_url": sandbox.base,
        "realm": realm,
        "client_secret": secret,
        "secret_path": "",
        "authz_client_id": client_id,
        "authz_client_secret": secret,
    }

    def by_identity(stable):
        rows = [
            sandbox.api("GET", realm, "users/" + row["id"]) for row in users.values()
        ]
        matched = [
            row
            for row in rows
            if (row.get("attributes") or {}).get("tr_identity_id") == [stable]
        ]
        if len(matched) != 1:
            raise LookupError("temporary identity is missing or ambiguous")
        return matched[0]

    class Directory:
        def _get(self, path):
            return sandbox.api("GET", realm, path)

        def user_by_identity_id(self, stable):
            return by_identity(stable)

    def evaluator():
        return KeycloakPolicyEvaluator(
            allowed_kinds={"research", "research_report"},
            allowed_scopes={"read", "manage", "share"},
            adapter=Directory(),
            settings=settings,
            request=lambda _adapter, client_uuid, body: sandbox.api(
                "POST",
                realm,
                f"clients/{client_uuid}/authz/resource-server/policy/evaluate",
                body,
            ),
        )

    grant_manager = KeycloakResearchGrantManager(
        settings_provider=lambda: settings,
        user_provider=lambda subject: sandbox.api("GET", realm, "users/" + subject),
        user_by_identity=by_identity,
        link_policy_evaluator=evaluator,
    )
    resolver = lambda name: {
        "identity_id": "stable-" + name,
        "subject": users[name]["id"],
    }
    with (
        tempfile.TemporaryDirectory(prefix="tr-browser-assistance-") as dirname,
        ExitStack() as stack,
    ):
        root = Path(dirname)
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "TRADERESEARCH_PUBLIC_SERVER": "1",
                    "TRADERESEARCH_SERVER_ID": "browser-qa",
                },
                clear=False,
            )
        )
        for target in [
            "server.identity.user_session.oidc_settings",
            "server.identity.keycloak_authorization.oidc_settings",
            "server.identity.server_admission.oidc_settings",
        ]:
            stack.enter_context(patch(target, lambda: settings))
        stack.enter_context(
            patch(
                "server.identity.federation_identity_sync.manager_keycloak_admin_adapter",
                Directory,
            )
        )
        state = manager.ManagerState(
            ROOT,
            sys.executable,
            server_role="main",
            server_id="browser-qa",
            state_root=root / "state",
            data_root=root / "data",
        )
        state.client_state = ClientStateService(
            client_root=root / "client", profile_cache_root=root / "profiles"
        )
        state.federated_public_data = state.client_state
        state.client_state.ensure_self_profile("member")
        state.client_state.ensure_self_profile("owner")
        legacy = ResearchCatalog(state.sessions_db_path)
        ref = legacy.create_research(owner_ref="owner", title="Temporary research")[
            "research_id"
        ]
        ensure_keycloak_resource(
            resource_type="research",
            resource_ref=ref,
            owner_subject=users["owner"]["id"],
        )
        catalog = ResearchCatalog(
            state.sessions_db_path,
            research_authorizer=KeycloakResearchAuthorization(),
            profile_authorizer=NoProfileGrants(),
            profile_grant_manager=grant_manager,
            profile_identity_resolver=resolver,
        )
        state.research_catalog = catalog

        class Handler(manager.Handler):
            def do_GET(self):
                if self.path == "/fixture":
                    body = b'<html><body><div id="root"></div></body></html>'
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return super().do_GET()

            def log_message(self, *_args):
                pass

        Handler.state = state
        server = manager.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel="chrome")
                owner_ctx = browser.new_context(
                    extra_http_headers={
                        "Authorization": "Bearer " + sessions["owner"][0]
                    },
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                member_ctx = browser.new_context(
                    extra_http_headers={
                        "Authorization": "Bearer " + sessions["member"][0]
                    },
                    viewport={"width": 390, "height": 844},
                    locale="zh-CN",
                )
                try:
                    origin = f"http://127.0.0.1:{server.server_address[1]}"

                    def load(ctx, fragment="", create=False):
                        page = ctx.new_page()
                        page.set_default_timeout(20000)
                        page.goto(origin + "/fixture" + fragment)
                        page.evaluate(
                            "(value) => {window.researchId = value.ref;window.testCreate = value.create}",
                            {"ref": ref, "create": create},
                        )
                        page.add_style_tag(path=str(stylesheet))
                        page.add_script_tag(path=str(bundle))
                        return page

                    creator = load(owner_ctx, create=True)
                    creator.get_by_text("新研究默认仅自己可见", exact=False).wait_for()
                    assert creator.get_by_text(
                        "此入口在服务器创建研究", exact=False
                    ).is_visible()
                    creator.get_by_role("textbox", name="名称").fill(
                        "Temporary private research"
                    )
                    creator.get_by_role("button", name="新建研究").click()
                    creator.wait_for_function(
                        "window.created?.research_id", timeout=30000
                    )
                    created = creator.evaluate("window.created.research_id")
                    assert created and created != ref
                    with identity_request():
                        bind_verified_identity(*sessions["owner"])
                        assert (
                            catalog.get_research_summary(created, viewer="owner")[
                                "access"
                            ]["can_manage"]
                            is True
                        )
                    import sqlite3

                    with sqlite3.connect(state.sessions_db_path) as db:
                        before = db.execute(
                            "SELECT COUNT(*) FROM research_catalog_researches"
                        ).fetchone()[0]
                        row = db.execute(
                            "SELECT visibility,authorized_users_json FROM research_catalog_researches WHERE research_id=?",
                            (created,),
                        ).fetchone()
                        assert row == ("private", "[]")
                    rejected = creator.evaluate(
                        """async () => (await fetch('/api/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'bad',visibility:'public'})})).status"""
                    )
                    assert rejected == 400
                    with sqlite3.connect(state.sessions_db_path) as db:
                        assert (
                            db.execute(
                                "SELECT COUNT(*) FROM research_catalog_researches"
                            ).fetchone()[0]
                            == before
                        )
                    state.research_catalog = legacy
                    try:
                        rejected = creator.evaluate(
                            """async () => (await fetch('/api/research/keycloak-create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'bad',visibility:'private',authorized_users:[]})})).status"""
                        )
                        assert rejected == 409
                    finally:
                        state.research_catalog = catalog
                    creator.close()
                    owner = load(owner_ctx)
                    owner.get_by_text(
                        "这里仅显示对此对象直接授予用户的权限", exact=False
                    ).wait_for()
                    owner.get_by_role("combobox", name="用户名").fill("member")
                    owner.get_by_role("checkbox", name="使用").check()
                    owner.get_by_role("button", name="授予权限").click()
                    owner.get_by_text("member", exact=True).first.wait_for()
                    member = load(member_ctx)
                    url = "/api/research/" + quote(ref, safe="")
                    status = lambda page: page.evaluate(
                        "async url => (await fetch(url)).status", url
                    )
                    assert status(member) == 200
                    owner.get_by_role("button", name="撤销", exact=True).first.click()
                    owner.get_by_text("撤销该用户的直接授权？").wait_for()
                    owner.locator(
                        ".ant-popconfirm-buttons:visible button.ant-btn-primary"
                    ).click()
                    owner.get_by_text("尚无直接授权").wait_for()
                    assert status(member) == 403
                    owner.get_by_role("tab", name="分享链接").click()
                    owner.get_by_role("button", name="创建链接").click()
                    field = owner.get_by_label("链接仅在创建时显示，请及时复制")
                    field.wait_for()
                    link = field.input_value()
                    fragment = "#" + link.split("#", 1)[1]
                    member.close()
                    member = load(member_ctx, fragment)
                    dialog = member.get_by_role("dialog", name="领取研究分享")
                    dialog.wait_for()
                    assert "research_share" not in member.url
                    dialog.get_by_role("button", name="确认领取").click()
                    dialog.wait_for(state="hidden")
                    assert status(member) == 200
                    owner.get_by_role("button", name="撤销", exact=True).first.click()
                    owner.get_by_text("撤销后不能再领取；已领取的权限保留。").wait_for()
                    owner.locator(
                        ".ant-popconfirm-buttons:visible button.ant-btn-primary"
                    ).click()
                    owner.get_by_text("已撤销", exact=True).wait_for()
                    assert status(member) == 200
                    print(
                        json.dumps(
                            {
                                "real_keycloak": True,
                                "real_manager_http": True,
                                "real_react_browser": True,
                                "safe_server_creation": True,
                                "server_creation_not_local": True,
                                "legacy_write_rejected": True,
                                "direct_grant_and_revoke_same_token": True,
                                "share_link_claim": True,
                                "revoke_preserves_claim": True,
                                "no_real_users_modified": True,
                                "profile_membership": "denial-only test double",
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                finally:
                    owner_ctx.close()
                    member_ctx.close()
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="tr-research-sharing-ui-") as directory:
        bundle = Path(directory) / "sharing.js"
        subprocess.run(
            [
                str(APP / "node_modules/.bin/esbuild"),
                str(
                    ROOT / "tests/scripts/fixtures/research_sharing_keycloak_smoke.tsx"
                ),
                "--bundle",
                "--format=iife",
                "--target=es2020",
                f"--outfile={bundle}",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with Sandbox() as sandbox:
            run(sandbox, bundle, bundle.with_suffix(".css"))
