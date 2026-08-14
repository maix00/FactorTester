"""Dependency-free authentication and compliance pages for Manager."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from urllib.parse import urlparse

from server.manager.domain.devices import PUBLIC_DEVICE_LIMIT
from server.manager.http.localization import page_localization


PUBLIC_REGISTRATION_NOTICE = (
    "根据工信部及通信管理相关网络信息服务合规要求，本公网实例暂不开放自助注册；"
    "如需账号，请联系本服务管理员。"
)

PUBLIC_DEVICE_COMPLIANCE_NOTICE = (
    "本公网入口仅向公司内网已登记的设备提供访问。根据工信部及通信管理相关"
    "网络信息服务合规要求，公网 IP/域名提供信息服务是否需要备案，应以主管"
    "部门和接入服务商核定为准。"
    "本系统不采集 MAC、IMEI、浏览器指纹、定位或原始 User-Agent 等设备画像；"
    "仅使用随机设备编号和公钥签名进行访问控制，并为安全审计记录粗粒度客户端"
    "名称、登记来源 IP、最近访问 IP 及时间。上述记录仅向对应用户和授权管理员"
    "显示，按最小必要原则处理。新设备不能在本合规页直接注册；请由"
    "已登录的公司内网 FactorTester 设置→设备白名单页面生成一次性公网设备授权"
    "链接，再在本公网地址打开。公网页面会为本来源重新生成设备密钥，私钥只保留"
    "在当前公网来源的浏览器不可导出存储中。授权链接短时有效且只能使用一次。"
    "每个用户最多登记三台公网服务器访问设备；公司内网设备不占用此公网名额。"
    "没有有效授权或已登记设备的访问只能看到本合规提示，未登记设备不开放登录或注册。"
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
            "/login", "/compliance", "/device-authorize", "/visitor",
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


def compliance_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
    visitor_entry_href: str = "",
) -> bytes:
    # The public compliance notice is a jurisdiction-specific Chinese notice,
    # so it deliberately does not vary with the requesting browser language.
    del accept_language
    locale, strings = page_localization("zh-Hans")
    messages = {
        "loading": _text(
            strings,
            "当前已登记的公网访问用户与设备数量：正在查询……（每个用户最多 {limit} 台设备）",
        ).replace("{limit}", str(PUBLIC_DEVICE_LIMIT)),
        "system": _text(
            strings,
            "当前系统已登记的公网访问用户数：{users}；设备数：{devices}（每用户最多 {limit} 台）。",
        ),
        "account": _text(
            strings,
            "当前账户已登记的公网访问用户数：{users}；设备数：{devices}（每用户最多 {limit} 台）。",
        ),
        "unavailable": _text(
            strings,
            "当前已登记的公网访问用户与设备数量：暂时无法查询。",
        ),
        "storageUnavailable": _text(strings, "设备凭证存储不可用"),
        "notApproved": _text(strings, "设备未获批准"),
        "checking": "正在检查本浏览器的设备凭证……",
        "authenticating": "检测到已登记设备，正在自动登录……",
        "noCredential": (
            "当前浏览器来源没有已登记的设备密钥。请使用登记时相同的浏览器和 "
            "HTTPS 地址，或从内网设置页为此浏览器重新授权。"
        ),
        "failed": (
            "设备自动登录失败。请确认设备仍在白名单中，或从内网设置页重新授权。"
        ),
        "success": "设备验证成功，正在进入 FactorTester……",
        "visitorEntry": (
            "以访客模式访问公网 IP（与内网未登录访问权限一致；仅显示本服务器最近 "
            "20 条测试任务，不提供生成物下载）"
        ),
    }
    visitor_entry = ""
    if visitor_entry_href:
        visitor_entry = (
            '<p class="visitor-entry"><a href="'
            + html.escape(visitor_entry_href, quote=True)
            + '">'
            + html.escape(messages["visitorEntry"])
            + "</a></p>"
        )
    return f"""<!doctype html><html lang="{html.escape(locale, quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>FactorTester</title></head>
<body style="margin:2rem;max-width:52rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.7"><p>{_html(strings, PUBLIC_DEVICE_COMPLIANCE_NOTICE)}</p>{visitor_entry}
<p id="public-device-count">{html.escape(messages["loading"])}</p>
<p id="device-auth-status" role="status" aria-live="polite">{html.escape(messages["checking"])}</p>
<script>
const nextPath={_script(safe_login_next(next_path))};const messages={_script(messages)};const format=(template,values)=>Object.entries(values).reduce((text,[key,value])=>text.split(`{{${{key}}}}`).join(String(value)),template);const b64=value=>{{const text=atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4));return Uint8Array.from(text,ch=>ch.charCodeAt(0));}};const b64url=value=>{{const bytes=new Uint8Array(value);let text="";for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text).replace(/\\+/g,"-").replace(/\\//g,"_").replace(/=+$/g,"");}};
const openDB=()=>new Promise((resolve,reject)=>{{if(!window.indexedDB)return reject(new Error(messages.storageUnavailable));const request=indexedDB.open("factortester-device",1);request.onupgradeneeded=()=>request.result.createObjectStore("credentials",{{keyPath:"device_id"}});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error||new Error(messages.storageUnavailable));}});
const credentials=async()=>{{const db=await openDB();return new Promise((resolve,reject)=>{{const values=[];const request=db.transaction("credentials").objectStore("credentials").openCursor();request.onsuccess=event=>{{const cursor=event.target.result;if(cursor){{values.push(cursor.value);cursor.continue();}}else{{db.close();resolve(values);}}}};request.onerror=()=>{{db.close();reject(request.error||new Error(messages.storageUnavailable));}};}});}};
const post=async(path,body)=>{{const response=await fetch(path,{{method:"POST",headers:{{"Content-Type":"application/json"}},credentials:"same-origin",cache:"no-store",body:JSON.stringify(body)}});let payload={{}};try{{payload=await response.json();}}catch{{}}if(!response.ok||!payload.success){{const error=new Error(payload.error||messages.notApproved);error.status=response.status;throw error;}}return payload;}};
const countLabel=document.querySelector("#public-device-count");const loadCount=async()=>{{try{{const response=await fetch("/api/device/summary",{{credentials:"same-origin",cache:"no-store"}});const payload=await response.json();if(!response.ok||!payload.success)throw new Error(messages.unavailable);const values={{users:Number(payload.public_user_count||0),devices:Number(payload.public_device_count||0),limit:Number(payload.public_device_limit||{PUBLIC_DEVICE_LIMIT})}};countLabel.textContent=format(payload.scope==="account"?messages.account:messages.system,values);}}catch(_){{countLabel.textContent=messages.unavailable;}}}};loadCount();
const statusLabel=document.querySelector("#device-auth-status");const setStatus=value=>{{statusLabel.textContent=value;}};const wait=delay=>new Promise(resolve=>setTimeout(resolve,delay));let authenticationRunning=false;
const authenticate=async()=>{{if(authenticationRunning)return;authenticationRunning=true;try{{const saved=await credentials();if(!saved.length){{setStatus(messages.noCredential);return;}}setStatus(messages.authenticating);for(const credential of saved){{for(const delay of [0,400,1200]){{if(delay)await wait(delay);try{{const challenge=await post("/api/device/challenge",{{device_id:credential.device_id}});const signature=await crypto.subtle.sign({{name:"ECDSA",hash:"SHA-256"}},credential.private_key,b64(challenge.challenge));await post("/api/device/verify",{{challenge_id:challenge.challenge_id,device_id:credential.device_id,public_key:credential.public_key,signature:b64url(signature)}});setStatus(messages.success);window.location.replace(nextPath);return;}}catch(error){{if(error?.status===403)break;}}}}}}setStatus(messages.failed);}}catch(_){{setStatus(messages.failed);}}finally{{authenticationRunning=false;}}}};
window.addEventListener("online",authenticate);document.addEventListener("visibilitychange",()=>{{if(document.visibilityState==="visible")authenticate();}});authenticate();
</script></body></html>""".encode("utf-8")


def device_gate_page(
    next_path: str = "/",
    *,
    accept_language: object = "",
) -> bytes:
    return compliance_page(next_path, accept_language=accept_language)


def device_authorization_page(
    token: str,
    next_path: str = "/",
    *,
    accept_language: object = "",
) -> bytes:
    """Render the short-lived, single-use public-origin enrollment page."""
    locale, strings = page_localization(accept_language)
    messages = {
        "storageUnsupported": _text(strings, "浏览器不支持设备凭证存储"),
        "storageUnavailable": _text(strings, "设备凭证存储不可用"),
        "storageFailed": _text(strings, "设备凭证保存失败"),
        "authorizationFailed": _text(strings, "设备授权失败"),
        "authorizationMissing": _text(strings, "授权链接缺失或已失效"),
        "keyUnsupported": _text(strings, "浏览器不支持设备密钥"),
        "success": _text(strings, "设备登记成功，正在进入 FactorTester……"),
    }
    return f"""<!doctype html><html lang="{html.escape(locale, quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>{_html(strings, "授权公网设备")} · FactorTester</title>
<style>{_CARD_STYLE}</style>
</head><body><main class="card"><h1>{_html(strings, "授权公网设备")}</h1>
<p>{_html(strings, "这是一个由 FactorTester 管理员创建的一次性设备授权。当前公网地址会生成独立的设备密钥，私钥不会上传服务器。")}</p>
<p>{_html(strings, "登记后系统会为安全审计记录粗粒度浏览器/客户端名称、登记来源 IP 和最近访问 IP；不会保存原始 User-Agent、浏览器指纹、MAC、IMEI 或定位。")}</p>
<div class="notice">{_html(strings, "授权链接只能使用一次，并将在短时间后失效。确认这是你主动从受信任的内网设置页发起的授权后继续。")}</div>
<form id="authorize-form"><label>{_html(strings, "设备名称（可选）")}<input name="device_name" maxlength="128" placeholder="{_html(strings, "例如：我的 Mac")}"></label>
<button type="submit">{_html(strings, "在此公网来源登记设备")}</button><div id="message" class="error" hidden></div></form></main>
<script>
const grantToken={_script(str(token or ""))};const nextPath={_script(safe_login_next(next_path))};const messages={_script(messages)};
try{{history.replaceState(null,"","/device-authorize");}}catch(_){{}}
const message=document.querySelector("#message");const form=document.querySelector("#authorize-form");const button=form.querySelector("button");
const openDB=()=>new Promise((resolve,reject)=>{{if(!window.indexedDB)return reject(new Error(messages.storageUnsupported));const request=indexedDB.open("factortester-device",1);request.onupgradeneeded=()=>request.result.createObjectStore("credentials",{{keyPath:"device_id"}});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error||new Error(messages.storageUnavailable));}});
const save=async value=>{{const db=await openDB();await new Promise((resolve,reject)=>{{const request=db.transaction("credentials","readwrite").objectStore("credentials").put(value);request.onsuccess=resolve;request.onerror=()=>reject(request.error||new Error(messages.storageFailed));}});db.close();}};
const remove=async id=>{{try{{const db=await openDB();await new Promise((resolve,reject)=>{{const request=db.transaction("credentials","readwrite").objectStore("credentials").delete(id);request.onsuccess=resolve;request.onerror=reject;}});db.close();}}catch(_){{}}}};
const post=async body=>{{const response=await fetch("/api/device/authorization/redeem",{{method:"POST",headers:{{"Content-Type":"application/json"}},credentials:"same-origin",cache:"no-store",body:JSON.stringify(body)}});let payload={{}};try{{payload=await response.json();}}catch{{}}if(!response.ok||!payload.success)throw new Error(payload.error||messages.authorizationFailed);return payload;}};
form.addEventListener("submit",async event=>{{event.preventDefault();button.disabled=true;message.hidden=true;let deviceId="";try{{if(!grantToken)throw new Error(messages.authorizationMissing);if(!window.crypto?.subtle)throw new Error(messages.keyUnsupported);const pair=await crypto.subtle.generateKey({{name:"ECDSA",namedCurve:"P-256"}},false,["sign"]);const publicKey=await crypto.subtle.exportKey("jwk",pair.publicKey);deviceId=window.crypto.randomUUID?window.crypto.randomUUID():`${{Date.now()}}-${{Math.random().toString(36).slice(2)}}`;await save({{device_id:deviceId,username:"",public_key:publicKey,private_key:pair.privateKey}});const payload=await post({{token:grantToken,device_id:deviceId,public_key:publicKey,device_name:form.elements.device_name.value.trim()}});await save({{device_id:deviceId,username:payload.username||"",public_key:publicKey,private_key:pair.privateKey}});message.className="ok";message.textContent=messages.success;message.hidden=false;window.location.replace(nextPath);}}catch(error){{if(deviceId)await remove(deviceId);message.className="error";message.textContent=error.message||messages.authorizationFailed;message.hidden=false;button.disabled=false;}}}});
</script></body></html>""".encode("utf-8")
