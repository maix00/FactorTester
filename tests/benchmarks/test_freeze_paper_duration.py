"""The reproduction helper must not silently substitute a different deviation family."""
import sqlite3
from types import SimpleNamespace
import pytest
from tests.benchmarks import freeze_paper_duration as module

@pytest.mark.parametrize('selected',['TsDurDev','TsDurDevDayScope'])
def test_explicit_family_selects_its_source_and_parameters(tmp_path,monkeypatch,selected):
 database=tmp_path/'sources.sqlite'
 with sqlite3.connect(database) as c:
  c.execute('create table factor_family_sources(factor_id,source_code)')
  c.executemany('insert into factor_family_sources values(?,?)',[(name,name) for name in ['SgChgPct','SgChgDurDay','TsDurDev','TsDurDevDayScope','TsHistCmp']])
 calls=[]
 class Expr:
  def semantic_fingerprint(self):return 'a'*64
 def load(source,name):
  class Family:
   expr=Expr();params=[]
   def get_factor(self,**params):
    calls.append((name,params))
    return SimpleNamespace(alias=name,expr=Expr())
  return Family,None
 monkeypatch.setattr(module,'_load_factor_family_from_source',load)
 monkeypatch.setattr(module,'normalize_factor_param_row',lambda family,params:params)
 result=module.freeze(database,'20d',deviation_family=selected)
 assert [name for name,_ in calls]==['SgChgPct','SgChgDurDay',selected,'TsHistCmp']
 assert calls[2][1].get('N')==('1d' if selected=='TsDurDev' else None)
 assert result['parameters']['deviation_family']==selected
 assert set(result['source_sha256'])=={'SgChgPct','SgChgDurDay',selected,'TsHistCmp'}

def test_unknown_deviation_family_is_rejected(tmp_path):
 database=tmp_path/'sources.sqlite'
 with sqlite3.connect(database) as c:
  c.execute('create table factor_family_sources(factor_id,source_code)')
 with pytest.raises(ValueError,match='unsupported duration'):
  module.freeze(database,'20d',deviation_family='invented')
