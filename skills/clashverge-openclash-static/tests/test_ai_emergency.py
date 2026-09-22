import importlib.util,sys
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('emergency_skill',Path(__file__).parents[1]/'scripts/clashverge_to_openclash.py')
s=importlib.util.module_from_spec(spec);sys.modules[spec.name]=s;spec.loader.exec_module(s)
def test_single_failed_candidate_keeps_explicit_unverified_emergency_entry():
 data={'proxies':[{'name':'Taiwan','type':'ss','server':'invalid','port':443,'cipher':'aes-128-gcm','password':'fixture'},{'name':'Other','type':'ss','server':'invalid','port':443,'cipher':'aes-128-gcm','password':'fixture'}], 'proxy-groups':[]}
 for prefix in ('GPT','Gemini'):
  for suffix,refs in [('候选',['Taiwan']),('手动',['Taiwan']),('专用',[prefix+'手动'])]:data['proxy-groups'].append({'name':prefix+suffix,'type':'select','proxies':refs})
 s.restrict_ai_group_members(data)
 g={x['name']:x for x in data['proxy-groups']}
 for prefix in ('GPT','Gemini'):
  assert 'AI应急（未验证）' in g[prefix+'专用']['proxies']
  assert g[prefix+'专用']['proxies'][0]==prefix+'手动'
  assert g[prefix+'候选']['proxies']==['Taiwan']
 assert g['AI应急（未验证）']['type']=='select'
 assert g['AI应急（未验证）']['proxies']==['Taiwan','Other']


def _valid_config():
 data={
  'proxies':[{'name':'Taiwan','type':'ss','server':'invalid','port':443}],
  'proxy-groups':s.build_groups(['Taiwan'],['Taiwan'],['Taiwan'],['Taiwan']),
  'rules':['MATCH,默认代理'],
 }
 s.restrict_ai_group_members(data)
 return data


def test_validator_accepts_legacy_without_emergency_group():
 data=_valid_config()
 data['proxy-groups']=[
  {**group,'proxies':[ref for ref in group['proxies'] if ref!='AI应急（未验证）']}
  for group in data['proxy-groups']
  if group['name']!='AI应急（未验证）'
 ]
 s.validate_config(data)


def test_validator_rejects_non_select_emergency_group():
 data=_valid_config()
 emergency=next(group for group in data['proxy-groups'] if group['name']=='AI应急（未验证）')
 emergency['type']='fallback'
 with pytest.raises(s.ConfigError,match='emergency group must be a select group'):
  s.validate_config(data)


def test_restrict_replaces_existing_emergency_without_source_order_drift():
 data=_valid_config()
 data['proxy-groups'].insert(
  0,
  {'name':'AI应急（未验证）','type':'select','proxies':['deleted','Taiwan']},
 )
 s.restrict_ai_group_members(data)
 names=[group['name'] for group in data['proxy-groups']]
 assert names.count('AI应急（未验证）')==1
 assert names[-1]=='AI应急（未验证）'
 assert next(group for group in data['proxy-groups'] if group['name']=='AI应急（未验证）')['proxies']==['Taiwan']
 first_groups=[dict(group,proxies=list(group['proxies'])) for group in data['proxy-groups']]
 s.restrict_ai_group_members(data)
 assert data['proxy-groups']==first_groups
