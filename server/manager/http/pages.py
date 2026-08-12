"""Dependency-free authentication and compliance pages for Manager."""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

from server.manager.domain.devices import PUBLIC_DEVICE_LIMIT


PUBLIC_REGISTRATION_NOTICE = (
    "根据工信部及通信管理相关网络信息服务合规要求，本公网实例暂不开放自助注册；"
    "如需账号，请联系本服务管理员。"
)

PUBLIC_DEVICE_COMPLIANCE_NOTICE = (
    "本公网入口仅向公司内网已登记的设备提供访问。根据工信部及通信管理相关"
    "网络信息服务合规要求，公网 IP/域名提供信息服务是否需要备案，应以主管"
    "部门和接入服务商核定为准。"
    "本系统不采集 MAC、IMEI、浏览器指纹、定位等设备画像；仅使用内网登记的"
    "随机设备编号和公钥签名进行访问控制。设备凭证与账户绑定时属于身份鉴别"
    "及访问控制数据，按最小必要原则处理。请在公司内网 FactorTester 的设置"
    "→设备白名单页面登记或撤销设备。每个用户最多登记三台公网服务器访问设备；"
    "公司内网设备不占用此公网名额。未登记设备不开放登录或注册。"
)


def safe_login_next(value: str) -> str:
    candidate = str(value or "/").strip()
    parsed = urlparse(candidate)
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.path in {"/login", "/device-gate", "/compliance"}
    ):
        return "/"
    return candidate or "/"


def login_page(next_path: str = "/") -> bytes:
    safe_next = safe_login_next(next_path)
    next_json = json.dumps(safe_next, ensure_ascii=False).replace("</", "<\\/")
    notice = html.escape(PUBLIC_REGISTRATION_NOTICE)
    return f"""<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Sign in to FactorTester</title>
<style>:root{{color-scheme:light dark}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f4f6;color:#111827;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.card{{width:min(420px,calc(100vw - 40px));box-sizing:border-box;padding:28px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;box-shadow:0 12px 35px #11182718}}h1{{margin:0 0 8px;font-size:24px}}p{{color:#4b5563;line-height:1.55}}.notice{{margin:18px 0;padding:12px;border:1px solid #f59e0b66;border-radius:8px;background:#fffbeb;color:#92400e;font-size:13px;line-height:1.55}}label{{display:block;margin:14px 0;font-size:14px}}input{{display:block;box-sizing:border-box;width:100%;margin-top:6px;padding:10px 11px;border:1px solid #d1d5db;border-radius:7px;font:inherit}}button{{width:100%;padding:10px 12px;border:0;border-radius:7px;background:#2563eb;color:#fff;font:inherit;cursor:pointer}}button:disabled{{opacity:.6;cursor:wait}}.error{{margin-top:12px;color:#b91c1c;font-size:13px}}</style>
</head><body><main class="card"><h1>登录 FactorTester</h1>
<p>Sign in to access research, jobs, and your workspace.</p>
<div class="notice">{notice}<br>公网访问需要使用管理员创建的账户。</div>
<form id="login-form"><label>用户名 / Username<input name="username" autocomplete="username" required></label>
<label>密码 / Password<input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">登录 / Sign in</button><div id="error" class="error" hidden></div></form></main>
<script>const nextPath={next_json};const form=document.querySelector("#login-form");const button=form.querySelector("button");const error=document.querySelector("#error");form.addEventListener("submit",async event=>{{event.preventDefault();error.hidden=true;button.disabled=true;try{{const response=await fetch("/auth/login",{{method:"POST",headers:{{"Content-Type":"application/json"}},credentials:"same-origin",body:JSON.stringify({{username:form.elements.username.value,password:form.elements.password.value}})}});const payload=await response.json();if(!response.ok||!payload.success)throw new Error(payload.error||"登录失败");window.location.replace(nextPath)}}catch(cause){{error.textContent=cause.message||"登录失败";error.hidden=false;button.disabled=false}}}});</script>
</body></html>""".encode("utf-8")


def compliance_page(next_path: str = "/") -> bytes:
    safe_next = safe_login_next(next_path)
    next_json = json.dumps(safe_next, ensure_ascii=False).replace("</", "<\\/")
    notice = html.escape(PUBLIC_DEVICE_COMPLIANCE_NOTICE)
    return f"""<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>FactorTester</title></head>
<body style="margin:2rem;max-width:52rem;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;line-height:1.7"><p>{notice}</p>
<p id="public-device-count">当前已登记的公网服务器访问设备数量：正在查询……（每个用户最多 {PUBLIC_DEVICE_LIMIT} 台）</p>
<script>
const nextPath={next_json};const b64=value=>{{const text=atob(value.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-value.length%4)%4));return Uint8Array.from(text,ch=>ch.charCodeAt(0));}};const b64url=value=>{{const bytes=new Uint8Array(value);let text="";for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text).replace(/\\+/g,"-").replace(/\\//g,"_").replace(/=+$/g,"");}};
const openDB=()=>new Promise((resolve,reject)=>{{if(!window.indexedDB)return reject(new Error("device storage unavailable"));const request=indexedDB.open("factortester-device",1);request.onupgradeneeded=()=>request.result.createObjectStore("credentials",{{keyPath:"device_id"}});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error||new Error("device storage unavailable"));}});
const credentials=async()=>{{const db=await openDB();return new Promise((resolve,reject)=>{{const values=[];const request=db.transaction("credentials").objectStore("credentials").openCursor();request.onsuccess=event=>{{const cursor=event.target.result;if(cursor){{values.push(cursor.value);cursor.continue();}}else{{db.close();resolve(values);}}}};request.onerror=()=>{{db.close();reject(request.error||new Error("device storage unavailable"));}};}});}};
const post=async(path,body)=>{{const response=await fetch(path,{{method:"POST",headers:{{"Content-Type":"application/json"}},credentials:"same-origin",body:JSON.stringify(body)}});let payload={{}};try{{payload=await response.json();}}catch{{}}if(!response.ok||!payload.success)throw new Error(payload.error||"device not approved");return payload;}};
const countLabel=document.querySelector("#public-device-count");const loadCount=async()=>{{try{{const response=await fetch("/api/device/summary",{{credentials:"same-origin",cache:"no-store"}});const payload=await response.json();if(!response.ok||!payload.success)throw new Error("count unavailable");const count=Number(payload.public_device_count||0);const limit=Number(payload.public_device_limit||{PUBLIC_DEVICE_LIMIT});const subject=payload.scope==="account"?"当前账户":"当前服务器";countLabel.textContent=`${{subject}}已登记的公网服务器访问设备数量：${{count}} / ${{limit}}。`;}}catch(_){{countLabel.textContent="当前已登记的公网服务器访问设备数量：暂时无法查询。";}}}};loadCount();
const authenticate=async()=>{{try{{for(const credential of await credentials()){{try{{const challenge=await post("/api/device/challenge",{{device_id:credential.device_id}});const signature=await crypto.subtle.sign({{name:"ECDSA",hash:"SHA-256"}},credential.private_key,b64(challenge.challenge));await post("/api/device/verify",{{challenge_id:challenge.challenge_id,device_id:credential.device_id,public_key:credential.public_key,signature:b64url(signature)}});window.location.replace(nextPath);return;}}catch(_){{}}}}}}catch(_){{}}}};authenticate();
</script></body></html>""".encode("utf-8")


def device_gate_page(next_path: str = "/") -> bytes:
    return compliance_page(next_path)
