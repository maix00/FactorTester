"""Dependency-free authentication and compliance pages for Manager."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from urllib.parse import urlparse

from server.manager.http.localization import page_localization


PUBLIC_REGISTRATION_NOTICE = (
    "根据工信部及通信管理相关网络信息服务合规要求，本公网实例暂不开放自助注册；"
    "如需账号，请联系本服务管理员。"
)

PUBLIC_DEVICE_COMPLIANCE_NOTICE = (
    "本公网入口只向服务器白名单用户及其已认证设备提供访问。根据工信部及"
    "通信管理相关网络信息服务合规要求，公网 IP/域名提供信息服务是否需要"
    "备案，应以主管部门和接入服务商核定为准。"
    "本系统不采集 MAC、IMEI、浏览器指纹、定位或原始 User-Agent 等设备画像；"
    "仅使用随机设备编号和公钥签名进行访问控制，并为安全审计记录粗粒度客户端"
    "名称、登记来源 IP、最近访问 IP 及时间。上述记录仅向对应用户和授权管理员"
    "显示，按最小必要原则处理。白名单用户应在本公网服务器的访客模式中使用"
    "自己的账号和密码登录；登录成功后，当前浏览器会自动生成设备密钥并登记，"
    "私钥只保留在当前浏览器的不可导出存储中。已登记白名单设备仍可由用户本人或"
    "超级管理员撤销。没有有效白名单或已认证设备的访问只能"
    "看到本合规提示，未授权用户不开放登录、注册或设备登记。"
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


def login_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
) -> bytes:
    locale, strings = page_localization(accept_language)
    safe_next = safe_login_next(next_path)
    login_error = _script(_text(strings, "登录失败"))
    return f"""<!doctype html>
<html lang="{html.escape(locale, quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{_html(strings, "登录 FactorTester")}</title>
<style>{_CARD_STYLE}</style>
</head><body><main class="card"><h1>{_html(strings, "登录 FactorTester")}</h1>
<p>{_html(strings, "登录后读取研究、任务和个人工作区；服务器管理能力会自动判断")}</p>
<div class="notice">{_html(strings, PUBLIC_REGISTRATION_NOTICE)}<br>{_html(strings, "公网访问需要使用管理员创建的账户。")}</div>
<form id="login-form"><label>{_html(strings, "用户名")}<input name="username" autocomplete="username" required></label>
<label>{_html(strings, "密码")}<input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">{_html(strings, "登录")}</button><div id="error" class="error" hidden></div></form></main>
<script>const nextPath={_script(safe_next)};const loginError={login_error};const form=document.querySelector("#login-form");const button=form.querySelector("button");const error=document.querySelector("#error");form.addEventListener("submit",async event=>{{event.preventDefault();error.hidden=true;button.disabled=true;try{{const response=await fetch("/auth/login",{{method:"POST",headers:{{"Content-Type":"application/json"}},credentials:"same-origin",body:JSON.stringify({{username:form.elements.username.value,password:form.elements.password.value}})}});const payload=await response.json();if(!response.ok||!payload.success)throw new Error(payload.error||loginError);window.location.replace(nextPath)}}catch(cause){{error.textContent=cause.message||loginError;error.hidden=false;button.disabled=false}}}});</script>
</body></html>""".encode("utf-8")


def _device_auth_script(
    next_path: str,
    messages: Mapping[str, str],
    *,
    device_bridge: str = "",
    device_bridge_fallback: str = "",
    device_bridge_redirect: str = "",
) -> str:
    """Render bounded, observable browser device authentication logic."""
    return (
        "const nextPath="
        + _script(next_path)
        + ";const deviceBridge="
        + _script(device_bridge)
        + ";const deviceBridgeFallback="
        + _script(device_bridge_fallback)
        + ";const deviceBridgeRedirect="
        + _script(device_bridge_redirect)
        + ";const messages="
        + _script(messages)
        + r""";
const format=(template,values)=>Object.entries(values).reduce((text,[key,value])=>text.split("{"+key+"}").join(String(value)),template);
const b64=value=>{const text=atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4));return Uint8Array.from(text,ch=>ch.charCodeAt(0));};
const b64url=value=>{const bytes=new Uint8Array(value);let text="";for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");};
const openDB=()=>new Promise((resolve,reject)=>{if(!window.indexedDB)return reject(Object.assign(new Error(messages.storageUnavailable),{stage:"storage"}));const request=indexedDB.open("factortester-device",1);request.onupgradeneeded=()=>request.result.createObjectStore("credentials",{keyPath:"device_id"});request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>db.close();resolve(db);};request.onerror=()=>reject(Object.assign(request.error||new Error(messages.storageUnavailable),{stage:"storage"}));});
const credentials=async()=>{const db=await openDB();return new Promise((resolve,reject)=>{const values=[];const transaction=db.transaction("credentials","readonly");const finish=(error,value)=>{db.close();if(error)reject(Object.assign(error,{stage:"storage"}));else resolve(value);};transaction.oncomplete=()=>finish(null,values);transaction.onerror=()=>finish(transaction.error||new Error(messages.storageUnavailable));transaction.onabort=()=>finish(transaction.error||new Error(messages.storageUnavailable));const request=transaction.objectStore("credentials").openCursor();request.onsuccess=event=>{const cursor=event.target.result;if(cursor){values.push(cursor.value);cursor.continue();}};request.onerror=()=>finish(request.error||new Error(messages.storageUnavailable));});};
const post=async(path,body,stage)=>{let response;try{response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},credentials:"same-origin",cache:"no-store",mode:"same-origin",redirect:"error",body:JSON.stringify(body)});}catch(cause){cause.stage=stage;cause.kind="network";throw cause;}let payload={};try{payload=await response.json();}catch{}if(!response.ok||!payload.success){const error=new Error(payload.error||messages.notApproved);error.status=response.status;error.stage=stage;throw error;}return payload;};
const countLabel=document.querySelector("#public-device-count");const loadCount=async()=>{try{const response=await fetch("/api/device/summary",{credentials:"same-origin",cache:"no-store"});const payload=await response.json();if(!response.ok||!payload.success)throw new Error(messages.unavailable);const values={users:Number(payload.public_user_count||0),devices:Number(payload.public_device_total_count??payload.public_device_count??0)};countLabel.textContent=format(payload.scope==="account"?messages.account:messages.system,values);}catch(_){countLabel.textContent=messages.unavailable;}};
const statusLabel=document.querySelector("#device-auth-status");const setStatus=value=>{statusLabel.textContent=value;};const wait=delay=>new Promise(resolve=>setTimeout(resolve,delay));const MAX_AUTHENTICATION_RUNS=2;let authenticationRuns=0;let authenticationRunning=false;let authenticationSucceeded=false;let lastAuthenticationError=null;let authenticationRetryTimer=0;
const failureMessage=error=>{const stage=String(error?.stage||"");if(error?.kind==="network")return messages[stage+"NetworkFailed"]||messages.networkFailed;const key=stage+"Failed";return messages[key]||messages.failed;};
const transientFailure=error=>error?.kind==="network"||[408,425,429,500,502,503,504].includes(Number(error?.status));
const scheduleAuthenticationRetry=()=>{if(authenticationSucceeded||authenticationRuns>=MAX_AUTHENTICATION_RUNS||!transientFailure(lastAuthenticationError)||authenticationRetryTimer)return;authenticationRetryTimer=setTimeout(()=>{authenticationRetryTimer=0;if(authenticationRunning||authenticationSucceeded)return;setStatus(messages.retrying||messages.authenticating);void authenticate();},2500);};
const bridgeBody=()=>deviceBridge?{device_bridge:deviceBridge}:{};const bridgeFallback=()=>{if(!deviceBridgeFallback)return false;setStatus(messages.bridgeFallback||messages.noCredential);window.location.replace(deviceBridgeFallback);return true;};const bridgeRedirect=()=>{if(!deviceBridgeRedirect)return false;setStatus(messages.bridgeRedirecting||messages.authenticating);window.location.replace(deviceBridgeRedirect);return true;};
const authenticate=async()=>{if(authenticationRunning||authenticationSucceeded||authenticationRuns>=MAX_AUTHENTICATION_RUNS)return;authenticationRunning=true;authenticationRuns+=1;let lastError=null;lastAuthenticationError=null;try{if(window.isSecureContext===false){const error=new Error(messages.transportFailed);error.stage="transport";lastError=error;setStatus(failureMessage(error));return;}let saved;try{saved=await credentials();}catch(error){lastError=error;setStatus(failureMessage(error));return;}if(!saved.length){if(bridgeRedirect())return;if(bridgeFallback())return;setStatus(messages.noCredential);return;}setStatus(messages.authenticating);for(const credential of saved){for(const delay of [0,400,1200]){if(delay)await wait(delay);try{const challenge=await post("/api/device/challenge",{device_id:credential.device_id},"challenge");let signature;try{signature=await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"},credential.private_key,b64(challenge.challenge));}catch(error){error.stage="signing";throw error;}const result=await post("/api/device/verify",{...bridgeBody(),challenge_id:challenge.challenge_id,device_id:credential.device_id,public_key:credential.public_key,signature:b64url(signature),next:nextPath},"verify");authenticationSucceeded=true;lastAuthenticationError=null;setStatus(messages.success);window.location.replace(result.handoff_url||nextPath);return;}catch(error){lastError=error;if(error?.status===403)break;}}}lastAuthenticationError=lastError;if(lastError?.status===403){if(bridgeRedirect())return;if(bridgeFallback())return;}setStatus(failureMessage(lastError));}catch(error){lastAuthenticationError=error;setStatus(failureMessage(error));}finally{authenticationRunning=false;scheduleAuthenticationRetry();}};
const startAuthentication=()=>{void authenticate().finally(loadCount);};
window.addEventListener("online",authenticate);document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")authenticate();});if(document.readyState==="complete")startAuthentication();else window.addEventListener("load",startAuthentication,{once:true});"""
    )


def compliance_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
    visitor_entry_href: str = "",
    device_bridge: str = "",
    device_bridge_fallback: str = "",
    device_bridge_redirect: str = "",
) -> bytes:
    # The public compliance notice is a jurisdiction-specific Chinese notice,
    # so it deliberately does not vary with the requesting browser language.
    del accept_language
    locale, strings = page_localization("zh-Hans")
    messages = {
        "loading": _text(
            strings,
            "当前已登记的公网访问用户与设备数量：正在查询……",
        ),
        "system": _text(
            strings,
            "当前系统已登记的公网访问用户数：{users}；设备数：{devices}。",
        ),
        "account": _text(
            strings,
            "当前账户已登记的公网访问用户数：{users}；设备数：{devices}。",
        ),
        "unavailable": _text(
            strings,
            "当前已登记的公网访问用户与设备数量：暂时无法查询。",
        ),
        "storageUnavailable": _text(strings, "设备凭证存储不可用"),
        "storageFailed": "设备凭证读取失败，请重新打开此页面。",
        "notApproved": _text(strings, "设备未获批准"),
        "checking": "正在检查本浏览器的设备凭证……",
        "authenticating": "检测到已登记设备，正在自动登录……",
        "retrying": "设备连接暂时失败，正在自动重试……",
        "noCredential": (
            "当前浏览器来源没有已登记的设备密钥。白名单用户请点击访客模式，"
            "使用自己的账号和密码登录；登录后当前浏览器会自动登记。"
        ),
        "bridgeRedirecting": "当前来源没有设备密钥，正在检查已登记的安全入口……",
        "bridgeFallback": "当前浏览器来源没有可用的已登记设备密钥。",
        "failed": (
            "设备自动登录失败。请确认设备仍在白名单中，或进入访客模式重新登录。"
        ),
        "challengeFailed": "获取设备挑战失败，请稍后重试。",
        "signingFailed": "设备密钥签名阶段失败，请使用登记时相同的浏览器来源。",
        "verifyFailed": "设备验证阶段失败，请确认设备仍在白名单中。",
        "networkFailed": "与公网服务器通信失败，请检查网络或证书信任。",
        "challengeNetworkFailed": "获取设备挑战时与公网服务器通信失败，请检查网络或证书信任。",
        "verifyNetworkFailed": "提交设备验证时与公网服务器通信失败，请检查网络或证书信任。",
        "transportFailed": "当前页面不是受信任的 HTTPS 安全来源，无法进行设备自动登录。",
        "success": "设备验证成功，正在进入 FactorTester……",
        "visitorEntry": (
            "以访客模式访问公网 IP（与内网未登录访问权限一致；仅显示本服务器最近 "
            "20 条测试任务，不提供生成物下载）"
        ),
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
    device_auth_script = _device_auth_script(
        safe_login_next(next_path),
        messages,
        device_bridge=device_bridge,
        device_bridge_fallback=device_bridge_fallback,
        device_bridge_redirect=device_bridge_redirect,
    )
    return f"""<!doctype html><html lang="{html.escape(locale, quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>FactorTester</title></head>
<body style="margin:2rem;max-width:52rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7"><p>{_html(strings, PUBLIC_DEVICE_COMPLIANCE_NOTICE)}</p>{visitor_entry}
<p id="public-device-count">{html.escape(messages["loading"])}</p>
<p id="device-auth-status" role="status" aria-live="polite">{html.escape(messages["checking"])}</p>
<script>{device_auth_script}</script></body></html>""".encode("utf-8")


def device_gate_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
) -> bytes:
    return compliance_page(next_path, accept_language=accept_language)
