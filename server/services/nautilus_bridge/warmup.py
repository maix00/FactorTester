"""Frozen run policy over alpha-owned history analysis; no factor mathematics."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class FactorWarmupSettings:
    mode:str='auto'
    data_start_utc:str|None=None
    diagnostic_only:bool=False
    def manifest(self):
        return dict(mode=self.mode,data_start_utc=self.data_start_utc,diagnostic_only=self.diagnostic_only)


def freeze_warmup_settings(value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-{'mode','data_start_utc','diagnostic_only'}:raise ValueError('invalid factor_warmup fields')
    mode=value.get('mode','auto')
    if mode not in {'auto','custom','disabled'}:raise ValueError('factor_warmup mode must be auto, custom, or disabled')
    diagnostic=value.get('diagnostic_only',False)
    if type(diagnostic) is not bool:raise ValueError('diagnostic_only must be boolean')
    start=value.get('data_start_utc')
    if mode=='custom':
        stamp=datetime.fromisoformat(str(start).replace('Z','+00:00')) if start else None
        if stamp is None or stamp.tzinfo is None:raise ValueError('custom warmup requires timezone-aware data_start_utc')
        start=stamp.astimezone(timezone.utc).isoformat()
    elif start is not None:raise ValueError('data_start_utc is only valid for custom warmup')
    if mode=='disabled' and not diagnostic:raise ValueError('disabled warmup is diagnostic_only, not a formal performance run')
    return FactorWarmupSettings(mode,start,diagnostic)


def resolve_run_warmup(spec,receipts, *, policy, trading_start_utc,end_utc):
    import pandas as pd
    from alpha.factor import warmup_requirements, required_history_start
    requirement=warmup_requirements(spec)
    start=pd.Timestamp(trading_start_utc).value;end=pd.Timestamp(end_utc).value
    result=dict(version=1,settings=policy.manifest(),requirements=requirement,
        trading_start_ns=start,performance_start_ns=start,performance_end_ns=end,
        performance_eligible=policy.mode!='disabled' and not policy.diagnostic_only,sources={})
    if policy.mode=='disabled':return result
    for product,receipt in receipts.items():
        sessions=[(s['start_ns'],s['end_ns'],s['bar_count']) for s in receipt.get('session_summaries',())]
        bound=required_history_start(requirement,trading_start_ns=start,sessions=sessions)
        selected=pd.Timestamp(policy.data_start_utc).value if policy.mode=='custom' else bound
        if selected>bound:raise ValueError(f'{product}: custom warmup starts after required history')
        coverage=sessions[0][0] if sessions else receipt['first_available_ns']
        if coverage>selected:raise ValueError(f'{product}: insufficient warmup coverage; need input at {pd.Timestamp(selected,unit="ns",tz="UTC")}')
        if int(receipt['last_available_ns'])>end:raise ValueError(f'{product}: source must freeze data no later than the performance end')
        if int(receipt['last_available_ns'])<start:raise ValueError(f'{product}: source has no observations in the formal interval')
        result['sources'][product]=dict(required_start_ns=bound,requested_data_start_ns=selected,actual_data_start_ns=coverage,
            last_available_ns=receipt['last_available_ns'],
            actual_first_available_ns=receipt['first_available_ns'])
    return result


def warmup_configuration_schema():
    return [dict(path='factor_warmup.mode',type='enum',default='auto',options=['auto','custom','disabled'],
                 label='因子预热',label_key='backtest.warmup.mode',section='data',
                 help='alpha从所有嵌套依赖推导完整窗口；disabled仅用于诊断，不产生正式绩效'),
            dict(path='factor_warmup.data_start_utc',type='datetime',label='预热数据起点',
                 label_key='backtest.warmup.dataStart',section='data',visible_when={'factor_warmup.mode':'custom'}),
            dict(path='factor_warmup.diagnostic_only',type='boolean',default=False,label='仅诊断',
                 label_key='backtest.warmup.diagnosticOnly',section='data')]
