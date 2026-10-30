"""Dependency-free authentication and compliance pages for Manager."""

from __future__ import annotations

import html
import json
import os
from collections.abc import Mapping
from urllib.parse import urlparse, urlsplit

from server.manager.http.localization import page_localization


PUBLIC_REGISTRATION_NOTICE = (
    "本公网实例已关闭自助注册。账户由管理员创建；"
    "访客模式使用受限身份，不等同于个人账户。"
)

PUBLIC_DEVICE_COMPLIANCE_NOTICE = (
    "本服务用于研究、测试和数据展示。使用时请遵守适用法律法规及服务规则，"
    "不得提交无权使用的数据或内容。服务会处理账户、任务配置与结果，以及"
    "提供服务和保障安全所需的信息。处理方式、保存期限和联系渠道以本部署公布的"
    "隐私政策为准。运营方应根据服务实际情况核实并公示适用的许可或备案信息。"
)

_MIIT_FILING_URL = "https://beian.miit.gov.cn/"


def public_compliance_information() -> dict[str, str]:
    """Return deployment-owned public legal metadata without inventing values."""
    values = {
        "service_operator": os.environ.get(
            "FACTORTESTER_PUBLIC_SERVICE_OPERATOR", ""
        ).strip()[:256],
        "icp_record": os.environ.get(
            "FACTORTESTER_PUBLIC_ICP_RECORD", ""
        ).strip()[:256],
        "security_record": os.environ.get(
            "FACTORTESTER_PUBLIC_SECURITY_RECORD", ""
        ).strip()[:256],
        "compliance_contact": os.environ.get(
            "FACTORTESTER_PUBLIC_COMPLIANCE_CONTACT", ""
        ).strip()[:256],
        "privacy_policy_url": os.environ.get(
            "FACTORTESTER_PUBLIC_PRIVACY_POLICY_URL", ""
        ).strip()[:2048],
    }
    privacy_url = values["privacy_policy_url"]
    try:
        parsed = urlsplit(privacy_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            values["privacy_policy_url"] = ""
    except ValueError:
        values["privacy_policy_url"] = ""
    return values


def _public_compliance_information_html(
    information: Mapping[str, str],
) -> str:
    labels = (
        ("service_operator", "服务运营主体"),
        ("icp_record", "ICP备案/许可信息"),
        ("security_record", "公安联网备案信息（如适用）"),
        ("compliance_contact", "合规联系渠道"),
    )
    rows = []
    for key, label in labels:
        value = str(information.get(key) or "").strip()
        if key == "icp_record" and not value:
            value = "请联系服务运营方核实适用信息"
        elif key == "security_record" and not value:
            continue
        elif not value:
            continue
        rows.append(
            "<dt>" + html.escape(label) + "</dt><dd>"
            + html.escape(value) + "</dd>"
        )
    privacy_url = str(information.get("privacy_policy_url") or "").strip()
    privacy = (
        '<p><a rel="noopener noreferrer" href="'
        + html.escape(privacy_url, quote=True)
        + '">查看部署方隐私政策</a></p>'
        if privacy_url else
        "<p>请联系服务运营方了解隐私政策及数据保存期限。</p>"
    )
    filing = (
        '<p><a rel="noopener noreferrer" href="'
        + _MIIT_FILING_URL
        + '">工信部备案管理系统</a></p>'
    )
    return (
        '<section class="public-compliance-info" aria-labelledby="public-compliance-title">'
        '<h2 id="public-compliance-title">公网服务信息</h2><dl>'
        + "".join(rows)
        + "</dl>"
        + filing
        + privacy
        + "</section>"
    )

_CARD_STYLE = """:root{color-scheme:light dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f4f6;color:#111827;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(520px,calc(100vw - 40px));box-sizing:border-box;padding:28px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;box-shadow:0 12px 35px #11182718}h1{margin:0 0 8px;font-size:24px}p{color:#4b5563;line-height:1.55}.notice{margin:18px 0;padding:12px;border:1px solid #f59e0b66;border-radius:8px;background:#fffbeb;color:#92400e;font-size:13px;line-height:1.55}label{display:block;margin:14px 0;font-size:14px}input{display:block;box-sizing:border-box;width:100%;margin-top:6px;padding:10px 11px;border:1px solid #d1d5db;border-radius:7px;font:inherit}button{width:100%;padding:10px 12px;border:0;border-radius:7px;background:#2563eb;color:#fff;font:inherit;cursor:pointer}button:disabled{opacity:.6;cursor:wait}.error{margin-top:12px;color:#b91c1c;font-size:13px}.ok{margin-top:12px;color:#047857;font-size:13px}"""


def _text(strings: Mapping[str, str], key: str) -> str:
    return str(strings.get(key) or key)


def _html(strings: Mapping[str, str], key: str) -> str:
    return html.escape(_text(strings, key))


def _script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def safe_login_next(value: str) -> str:
    candidate = str(value or "/").strip()
    parsed = urlparse(candidate)
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.path in {
            "/login", "/compliance", "/visitor",
        }
    ):
        return "/"
    return candidate or "/"


def _device_auth_script(
    next_path: str,
    messages: Mapping[str, str],
) -> str:
    """Render bounded, observable browser device authentication logic."""
    return (
        "const nextPath="
        + _script(next_path)
        + ";const messages="
        + _script(messages)
        + r""";
const b64=value=>{const text=atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4));return Uint8Array.from(text,ch=>ch.charCodeAt(0));};
const b64url=value=>{const bytes=new Uint8Array(value);let text="";for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");};
const openDB=()=>new Promise((resolve,reject)=>{if(!window.indexedDB)return reject(Object.assign(new Error(messages.storageUnavailable),{stage:"storage"}));const request=indexedDB.open("factortester-device",1);request.onupgradeneeded=()=>request.result.createObjectStore("credentials",{keyPath:"device_id"});request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>db.close();resolve(db);};request.onerror=()=>reject(Object.assign(request.error||new Error(messages.storageUnavailable),{stage:"storage"}));});
const credentials=async()=>{const db=await openDB();return new Promise((resolve,reject)=>{const values=[];const transaction=db.transaction("credentials","readonly");const finish=(error,value)=>{db.close();if(error)reject(Object.assign(error,{stage:"storage"}));else resolve(value);};transaction.oncomplete=()=>finish(null,values);transaction.onerror=()=>finish(transaction.error||new Error(messages.storageUnavailable));transaction.onabort=()=>finish(transaction.error||new Error(messages.storageUnavailable));const request=transaction.objectStore("credentials").openCursor();request.onsuccess=event=>{const cursor=event.target.result;if(cursor){values.push(cursor.value);cursor.continue();}};request.onerror=()=>finish(request.error||new Error(messages.storageUnavailable));});};
const post=async(path,body,stage)=>{let response;try{response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},credentials:"same-origin",cache:"no-store",mode:"same-origin",redirect:"error",body:JSON.stringify(body)});}catch(cause){cause.stage=stage;cause.kind="network";throw cause;}let payload={};try{payload=await response.json();}catch{}if(!response.ok||!payload.success){const error=new Error(payload.error||messages.notApproved);error.status=response.status;error.stage=stage;throw error;}return payload;};
const statusLabel=document.querySelector("#device-auth-status");const setStatus=value=>{statusLabel.textContent=value;};const wait=delay=>new Promise(resolve=>setTimeout(resolve,delay));const MAX_AUTHENTICATION_RUNS=2;let authenticationRuns=0;let authenticationRunning=false;let authenticationSucceeded=false;let lastAuthenticationError=null;let authenticationRetryTimer=0;
const failureMessage=error=>{const stage=String(error?.stage||"");if(error?.kind==="network")return messages[stage+"NetworkFailed"]||messages.networkFailed;const key=stage+"Failed";return messages[key]||messages.failed;};
const transientFailure=error=>error?.kind==="network"||[408,425,429,500,502,503,504].includes(Number(error?.status));
const scheduleAuthenticationRetry=()=>{if(authenticationSucceeded||authenticationRuns>=MAX_AUTHENTICATION_RUNS||!transientFailure(lastAuthenticationError)||authenticationRetryTimer)return;authenticationRetryTimer=setTimeout(()=>{authenticationRetryTimer=0;if(authenticationRunning||authenticationSucceeded)return;setStatus(messages.retrying||messages.authenticating);void authenticate();},2500);};
const authenticate=async()=>{if(authenticationRunning||authenticationSucceeded||authenticationRuns>=MAX_AUTHENTICATION_RUNS)return;authenticationRunning=true;authenticationRuns+=1;let lastError=null;lastAuthenticationError=null;try{if(window.isSecureContext===false){const error=new Error(messages.transportFailed);error.stage="transport";lastError=error;setStatus(failureMessage(error));return;}let saved;try{saved=await credentials();}catch(error){lastError=error;setStatus(failureMessage(error));return;}if(!saved.length){setStatus(messages.noCredential);return;}setStatus(messages.authenticating);for(const credential of saved){for(const delay of [0,400,1200]){if(delay)await wait(delay);try{const challenge=await post("/api/device/challenge",{device_id:credential.device_id},"challenge");let signature;try{signature=await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"},credential.private_key,b64(challenge.challenge));}catch(error){error.stage="signing";throw error;}const verified=await post("/api/device/verify",{challenge_id:challenge.challenge_id,device_id:credential.device_id,public_key:credential.public_key,signature:b64url(signature),next:nextPath},"verify");authenticationSucceeded=true;lastAuthenticationError=null;setStatus(messages.success);window.location.replace(verified.login_url||nextPath);return;}catch(error){lastError=error;if(error?.status===403)break;}}}lastAuthenticationError=lastError;setStatus(failureMessage(lastError));}catch(error){lastAuthenticationError=error;setStatus(failureMessage(error));}finally{authenticationRunning=false;scheduleAuthenticationRetry();}};
const startAuthentication=()=>{void authenticate();};
window.addEventListener("online",authenticate);document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")authenticate();});if(document.readyState==="complete")startAuthentication();else window.addEventListener("load",startAuthentication,{once:true});"""
    )


def compliance_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
    visitor_entry_href: str = "",
    public_server: bool = False,
    compliance_information: Mapping[str, str] | None = None,
) -> bytes:
    # The public compliance notice is a jurisdiction-specific Chinese notice,
    # so it deliberately does not vary with the requesting browser language.
    del accept_language
    locale, strings = page_localization("zh-Hans")
    messages = {
        "storageUnavailable": _text(strings, "暂时无法确认设备状态"),
        "storageFailed": "无法确认当前访问状态，请刷新页面重试。",
        "notApproved": _text(strings, "当前无法自动登录，请使用账户登录。"),
        "checking": "正在确认访问状态……",
        "authenticating": "正在登录……",
        "retrying": "连接暂时不可用，正在重试……",
        "noCredential": (
            "请使用账户登录，或以受限访客身份继续。"
        ),
        "failed": "无法自动登录，请使用账户登录或稍后重试。",
        "challengeFailed": "登录未完成，请稍后重试。",
        "signingFailed": "登录未完成，请使用账户重新登录。",
        "verifyFailed": "无法确认登录状态，请重新登录。",
        "networkFailed": "暂时无法连接服务，请检查网络后重试。",
        "challengeNetworkFailed": "暂时无法连接服务，请检查网络后重试。",
        "verifyNetworkFailed": "暂时无法连接服务，请检查网络后重试。",
        "transportFailed": "请通过安全连接访问服务后重试。",
        "success": "登录成功，正在进入 TradeResearch……",
        "visitorEntry": "以受限访客身份继续",
        "visitorTestingOnly": "仅供测试使用",
    }
    visitor_entry = ""
    if visitor_entry_href:
        visitor_entry = (
            '<p class="visitor-entry"><a href="'
            + html.escape(visitor_entry_href, quote=True)
            + '">'
            + html.escape(messages["visitorEntry"])
            + '</a> <span class="visitor-test-note" style="margin-left:.5rem;color:#92400e;font-size:.85em">（'
            + html.escape(messages["visitorTestingOnly"])
            + "）</span></p>"
        )
    compliance_information_html = (
        _public_compliance_information_html(
            compliance_information or public_compliance_information()
        )
        if public_server else ""
    )
    device_auth_script = _device_auth_script(
        safe_login_next(next_path),
        messages,
    )
    return f"""<!doctype html><html lang="{html.escape(locale, quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>TradeResearch</title></head>
<body style="margin:2rem;max-width:52rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7"><p>{_html(strings, PUBLIC_DEVICE_COMPLIANCE_NOTICE)}</p>{compliance_information_html}{visitor_entry}
<p id="device-auth-status" role="status" aria-live="polite">{html.escape(messages["checking"])}</p>
<script>{device_auth_script}</script></body></html>""".encode("utf-8")


def device_gate_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
) -> bytes:
    return compliance_page(next_path, accept_language=accept_language)
