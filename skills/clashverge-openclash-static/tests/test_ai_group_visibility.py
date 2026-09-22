import importlib.util
import sys
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('visibility_converter',Path(__file__).parents[1]/'scripts/clashverge_to_openclash.py')
s=importlib.util.module_from_spec(spec);sys.modules[spec.name]=s;spec.loader.exec_module(s)

@pytest.mark.parametrize('command',['all','update-candidate'])
def test_update_defaults_incremental_but_full_retest_explicit(command):
 assert s.build_parser().parse_args([command]).full_retest is False
 assert s.build_parser().parse_args([command,'--full-retest']).full_retest is True

def data():
 groups=[]
 for prefix in ['GPT','Gemini']:
  groups.extend([{'name':prefix+'候选','proxies':['Taiwan','香港住宅','🇭🇰测试','Hong Kong 1','HK-2']},{'name':prefix+'手动','proxies':['UNKNOWN','bad','香港住宅',prefix+'历史LKG']},{'name':prefix+'专用','proxies':[prefix+'手动',prefix+'历史LKG']},{'name':prefix+'历史LKG','proxies':['bad']}])
 groups.append({'name':'手动选择','proxies':['Taiwan','香港住宅','UNKNOWN','bad']})
 return {'proxies':[{'name':name} for name in ['Taiwan','香港住宅','🇭🇰测试','Hong Kong 1','HK-2','UNKNOWN','bad']], 'proxy-groups':groups}

def test_unknown_and_hk_not_reachable_from_ai_selectors_but_remain_general():
 d=data();s.restrict_ai_group_members(d);g={x['name']:x for x in d['proxy-groups']}
 for prefix in ['GPT','Gemini']:
  assert g[prefix+'候选']['proxies']==['Taiwan']
  assert g[prefix+'手动']['proxies']==['Taiwan',prefix+'候选']
  assert g[prefix+'专用']['proxies']==[prefix+'手动',prefix+'候选','AI应急（未验证）']
  assert prefix+'历史LKG' not in g
 assert g['AI应急（未验证）']['type']=='select'
 assert g['AI应急（未验证）']['proxies']==['Taiwan','香港住宅','🇭🇰测试','Hong Kong 1','HK-2','UNKNOWN','bad']
 assert g['手动选择']['proxies']==['Taiwan','香港住宅','UNKNOWN','bad']

def test_empty_ai_pool_fails_closed():
 d=data();d['proxy-groups'][0]['proxies']=['HK-1']
 with pytest.raises(s.ConfigError,match='BLOCKED_NO_CURRENT_SERVICE_CANDIDATES'):
  s.restrict_ai_group_members(d)
