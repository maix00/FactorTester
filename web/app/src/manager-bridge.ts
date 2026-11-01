/** The native client owns the selected Manager and its authenticated session.
 * A WebKit handler is merely transport, never evidence of authorization. */
export const MANAGER_BRIDGE_SCHEMA = "tr-manager-bridge:v1";
export type ManagerAuthState = "authorized" | "unauthorized" | "unavailable";
export type ManagerConnection = {url:string;auth_state:ManagerAuthState};
type Handler = {postMessage:(message:Record<string,unknown>)=>unknown};
type Host = {webkit?:{messageHandlers?:{tradeResearchManager?:unknown}}};

export class ManagerBridgeError extends Error {
  readonly code:string;
  constructor(code:string){super(code);this.name="ManagerBridgeError";this.code=code;}
}
function record(value:unknown):value is Record<string,unknown>{return !!value && typeof value==="object" && !Array.isArray(value);}

/** Validate syntax only. The native client must also validate destination and origin. */
export function managerURL(value:unknown):string {
  if(typeof value!=="string" || value.length>2048 || value!==value.trim() || /[\u0000-\u001f\u007f]/.test(value))throw new ManagerBridgeError("manager_invalid_url");
  try {
    const url=new URL(value);
    if(!["http:","https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname!=="/")throw new Error("invalid");
    return url.href.replace(/\/+$/,"");
  }catch{throw new ManagerBridgeError("manager_invalid_url");}
}
/** Compare normalized endpoints without treating an incomplete form as equal. */
export function sameManagerURL(left:unknown,right:unknown):boolean {
  try{return managerURL(left)===managerURL(right);}catch{return false;}
}
function connection(value:Record<string,unknown>):ManagerConnection {
  let url:string;
  try{url=managerURL(value.url);}catch{throw new ManagerBridgeError("manager_invalid_response");}
  const auth_state=value.auth_state;
  if(auth_state!=="authorized" && auth_state!=="unauthorized" && auth_state!=="unavailable")throw new ManagerBridgeError("manager_invalid_response");
  return {url,auth_state};
}
export function managerBridge(host:unknown):ManagerClient|null {
  if(!record(host))return null;
  const handler=(host as Host).webkit?.messageHandlers?.tradeResearchManager;
  if(!record(handler) || typeof handler.postMessage!=="function")return null;
  return new ManagerClient(handler as Handler);
}

export class ManagerClient {
  private generation=0;
  private actions:Set<string>|null=null;
  private closed=false;
  private sequence=0;
  private switching=false;
  private readonly handler:Handler;
  constructor(handler:Handler){this.handler=handler;}
  close():void{this.closed=true;this.generation++;this.actions=null;}
  snapshot():number{return this.generation;}
  isCurrent(value:number):boolean{return !this.closed && value===this.generation;}
  supports(action:string):boolean{return !this.closed && !!this.actions?.has(action);}
  async capabilities():Promise<void>{
    const generation=this.generation,sequence=++this.sequence;
    this.actions=null;
    const reply=await this.call({action:"capabilities"});
    if(!this.isCurrent(generation)||sequence!==this.sequence)throw new ManagerBridgeError("manager_session_changed");
    if(!Array.isArray(reply.actions) || reply.actions.some(value=>typeof value!=="string" || value.length>64) || new Set(reply.actions).size!==reply.actions.length)throw new ManagerBridgeError("manager_invalid_response");
    const actions=new Set<string>(reply.actions);
    if(!actions.has("current") || !actions.has("switch"))throw new ManagerBridgeError("manager_capability_unavailable");
    this.actions=actions;
  }
  async current():Promise<ManagerConnection>{
    this.require("current");const generation=this.generation,sequence=this.sequence;
    const reply=await this.call({action:"current"});this.requireSnapshot(generation,sequence);
    return connection(reply);
  }
  async enrollDevice():Promise<void>{
    this.require("enroll_device");
    const generation=this.generation,sequence=this.sequence;
    await this.call({action:"enroll_device"});this.requireSnapshot(generation,sequence);
  }
  /** Native must clear the old session, validate the target, and navigate.
   * The caller must not treat a dispatched request as a completed switch. */
  async switchTo(input:string):Promise<ManagerConnection>{
    this.require("switch");
    if(this.switching)throw new ManagerBridgeError("manager_switch_pending");
    // Invalidate a slow current() response before handing the switch to native.
    const url=managerURL(input),generation=this.generation,sequence=++this.sequence;
    this.switching=true;
    try{
      const reply=await this.call({action:"switch",url});this.requireSnapshot(generation,sequence);
      const value=connection(reply);
      if(value.url!==url)throw new ManagerBridgeError("manager_invalid_response");
      return value;
    }finally{this.switching=false;}
  }
  private require(action:string):void{if(this.closed)throw new ManagerBridgeError("manager_client_closed");if(!this.actions?.has(action))throw new ManagerBridgeError("manager_capability_unavailable");}
  private requireSnapshot(generation:number,sequence:number):void{if(!this.isCurrent(generation)||sequence!==this.sequence||!this.actions)throw new ManagerBridgeError("manager_session_changed");}
  private async call(message:Record<string,unknown>):Promise<Record<string,unknown>>{
    if(this.closed)throw new ManagerBridgeError("manager_client_closed");
    const generation=this.generation;let result:unknown;
    try{result=await this.handler.postMessage(message);}catch{if(!this.isCurrent(generation))throw new ManagerBridgeError("manager_session_changed");throw new ManagerBridgeError("manager_bridge_failed");}
    if(!this.isCurrent(generation))throw new ManagerBridgeError("manager_session_changed");
    if(!record(result))throw new ManagerBridgeError("manager_invalid_response");
    if(result.success===false)throw new ManagerBridgeError(typeof result.code==="string"&&/^[a-z][a-z0-9_]{0,63}$/.test(result.code)?result.code:"manager_bridge_failed");
    if(result.success!==true || result.schema!==MANAGER_BRIDGE_SCHEMA)throw new ManagerBridgeError("manager_invalid_response");
    return result;
  }
}
