import React,{useEffect,useState} from "react";
import {AutoComplete,Form,Input,Select,Space,Tooltip} from "antd";
import {InfoCircleOutlined} from "@ant-design/icons";
import {useTranslation} from "react-i18next";
import {parameterLabel} from "../factor-parameters.ts";
import {FactorPicker} from "./library-picker.tsx";
type Row=Record<string,any>;
function NestedFactorInput({definition,value,onChange,disabled,onPendingChange}:{definition:Row;value:unknown;onChange:(value:unknown)=>void;disabled:boolean;onPendingChange:(value:boolean)=>void}):React.ReactElement {
 const {t}=useTranslation();
 const ref=value&&typeof value==='object'?String((value as Row).ref||(value as Row).factor_ref||''):typeof value==='string'&&value.startsWith('factor:v2:')?value:'';
 const [mode,setMode]=useState(ref?'factor':'value');
 return <div className="tr-factor-parameter-input"><Select aria-label={`${parameterLabel(definition)} ${t("editor.inputKind")}`} value={mode} disabled={disabled} onChange={next=>{setMode(next);onChange('');}}
  options={[{value:'value',label:t('editor.literal')},{value:'factor',label:t('catalog.factors')}]}/>
 {mode==='factor'?<FactorPicker label={parameterLabel(definition)} value={ref} disabled={disabled} onSelect={onChange} onPendingChange={onPendingChange}/>:
 <AutoComplete aria-label={parameterLabel(definition)} value={typeof value==='object'?'':String(value??'')} disabled={disabled} options={definition.options||[]} onChange={onChange}/>}</div>;
}
export function FactorParameters({definitions,values,onChange,disabled=false,onPendingChange}:{definitions:Row[];values:Row;onChange:(values:Row)=>void;disabled?:boolean;onPendingChange?:(value:boolean)=>void}):React.ReactElement {
 useEffect(()=>()=>onPendingChange?.(false),[onPendingChange]);
 const {t}=useTranslation();
 const [pending,setPending]=useState<Set<string>>(()=>new Set());
 useEffect(()=>{onPendingChange?.(pending.size>0);},[pending,onPendingChange]);
 return <>{definitions.filter(row=>row.alias).map(definition=>{
  const alias=String(definition.alias),label=parameterLabel(definition),value=values[alias];
  const update=(next:unknown):void=>onChange({...values,[alias]:next});
  const options:Array<{value:string;label:string}>=(definition.options||[]).map((option:{value:string;label:string})=>alias==="$Rev"?{...option,label:t(String(option.value)==="1"?"editor.reversalOn":"editor.reversalOff")}:option);
  const selected=typeof value==='boolean'?(value?'1':'0'):value==null?undefined:String(value);
  return <Form.Item key={alias} label={<Space size={6}>{label}{definition.desc?<Tooltip title={definition.desc}><InfoCircleOutlined/></Tooltip>:null}</Space>}>
   {definition.type==='FactorParam'?<NestedFactorInput key={alias} definition={definition} value={value} onChange={update} disabled={disabled} onPendingChange={busy=>setPending(current=>{if(current.has(alias)===busy)return current;const next=new Set(current);if(busy)next.add(alias);else next.delete(alias);return next;})}/>:
    definition.input_mode==='enum'?<Select aria-label={label} disabled={disabled} value={selected} options={options} onChange={update}/>:
    definition.input_mode==='enum_custom'?<AutoComplete aria-label={label} disabled={disabled} value={selected} options={options} onChange={update}/>:
    <Input aria-label={label} disabled={disabled} value={selected??''} onChange={event=>update(event.target.value)}/>}
  </Form.Item>;
 })}</>;
}
