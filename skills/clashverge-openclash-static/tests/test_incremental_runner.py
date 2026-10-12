import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml

root=Path(__file__).parents[1]/'scripts'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
s=load('incremental_runner_converter',root/'clashverge_to_openclash.py')
r=load('incremental_runner_test',root/'incremental_runner.py')
u=load('incremental_update_test',root/'incremental_update.py')

def report(manifest,names,kind):
 rows=[{'exact_node_id':x['exact_node_id'],'exact_node_name':x['exact_node_name'],'source_snapshot_id':'snap','source_hash':'hash','result':'PASS_SUPPORTED_REGION'} for x in manifest['nodes'] if x['exact_node_name'] in names]
 d={'source_snapshot_id':'snap','source_hash':'hash','production_fingerprint_preserved':True,('node_attempts' if kind=='rrc' else 'nodes'):rows}
 if kind=='rrc':d.update(status='COMPLETE',attribution_mismatch=0,auto_calibration_status='PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_AUTO_CALIBRATION',results=[],systemic_gate_confirmations=[])
 return d

def test_actual_use_admissions_require_current_exact_proof():
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[
     {'exact_node_id':'gpt-id','exact_node_name':'GPT-NEW'},
     {'exact_node_id':'gemini-id','exact_node_name':'GEMINI-NEW'},
     {'exact_node_id':'stream-id','exact_node_name':'流媒体-NEW'},
 ]}
 proof=lambda service,name,node_id,**extra:{
     'service':service,'node':name,'exact_node_id':node_id,
     'source_snapshot_id':'snap','source_hash':'hash','result':'PASS',
     'method':'desktop-web-route-marker-v1','marker_verified':True,
     'route_confirmed':True,**extra}
 rows=[
     proof('gemini','GEMINI-NEW','gemini-id'),
     proof('gpt','GPT-NEW','wrong-id'),
     proof('gpt','流媒体-NEW','stream-id'),
     proof('gpt','GPT-NEW','gpt-id',route_confirmed=False),
     proof('gpt','GPT-NEW','gpt-id'),
 ]
 assert r.actual_use_admissions(rows,m,['GPT-NEW','GEMINI-NEW','流媒体-NEW'],['GPT-NEW','GEMINI-NEW']) == {
     'gpt':['GPT-NEW'],'gemini':['GEMINI-NEW']}


def test_gemini_antigravity_hong_kong_pass_is_admitted_but_not_for_gpt():
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[
     {'exact_node_id':'hk-id','exact_node_name':'🇭🇰香港-CloudCode'},
 ]}
 proof=lambda service,method:{
     'service':service,'node':'🇭🇰香港-CloudCode','exact_node_id':'hk-id',
     'source_snapshot_id':'snap','source_hash':'hash','result':'PASS',
     'method':method,'marker_verified':True,'route_confirmed':True}
 assert r.actual_use_admissions(
     [proof('gemini','antigravity_inference')],
     m,
     ['🇭🇰香港-CloudCode'],
     ['🇭🇰香港-CloudCode'],
 ) == {'gpt': [], 'gemini': ['🇭🇰香港-CloudCode']}
 assert r.actual_use_admissions(
     [proof('gpt','antigravity_inference')],
     m,
     ['🇭🇰香港-CloudCode'],
     ['🇭🇰香港-CloudCode'],
 ) == {'gpt': [], 'gemini': []}


def test_registry_preferred_names_require_current_exact_identity(monkeypatch, tmp_path):
    key = b'incremental-registry-test-key-0123456789'
    old_renamed = {
        'name': 'old-renamed', 'type': 'ss', 'server': 'same.example', 'port': 1
    }
    old_same_name = {
        'name': 'same-name', 'type': 'ss', 'server': 'old.example', 'port': 2
    }
    removed = {
        'name': 'removed', 'type': 'ss', 'server': 'removed.example', 'port': 3
    }
    source = {
        'proxies': [
            {
                'name': 'same-name',
                'type': 'ss',
                'server': 'new.example',
                'port': 2,
            },
            {
                'name': 'renamed-current',
                'type': 'ss',
                'server': 'same.example',
                'port': 1,
            },
        ]
    }
    entries = [
        {
            'exact_node_id': s.stable_node_identity(proxy, key),
            'node': proxy['name'],
            'service': 'gpt',
            'tier': 'preferred',
            'enabled': True,
            'tested_at': '2026-10-10T00:00:00+00:00',
            'method': 'chatgpt_guest_generation',
        }
        for proxy in (old_renamed, old_same_name, removed)
    ]
    registry_path = tmp_path / 'verified-service-registry.json'
    registry_path.write_text(json.dumps({'schema_version': 1, 'nodes': entries}))
    key_path = tmp_path / 'source-identity.key'
    key_path.write_bytes(key)
    monkeypatch.setenv('OPENCLASH_VERIFIED_REGISTRY_PATH', str(registry_path))
    monkeypatch.setattr(s, 'DEFAULT_SOURCE_IDENTITY_KEY', key_path)

    assert r.verified_registry_preferred_names(s, source, key_path) == {
        'gpt': ['renamed-current'],
        'gemini': [],
    }

def test_manual_region_blocks_require_current_exact_failure_evidence():
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[
     {'exact_node_id':'gpt-id','exact_node_name':'GPT-NODE'},
     {'exact_node_id':'gemini-id','exact_node_name':'GEMINI-NODE'},
 ]}
 row=lambda service,name,node_id,**extra:{
     'service':service,'node':name,'exact_node_id':node_id,
     'source_snapshot_id':'snap','source_hash':'hash','result':'FAIL',
     'method':'desktop-web-route-marker-v1','route_confirmed':True,
     'error_category':'FAIL_REGION',**extra}
 rows=[
     row('gpt','GPT-NODE','gpt-id'),
     row('gemini','GEMINI-NODE','gemini-id',error_category='FAIL_FORBIDDEN_LOCATION'),
     row('gpt','GPT-NODE','gpt-id',source_hash='old-hash'),
     row('gpt','GPT-NODE','wrong-id'),
     row('gpt','GPT-NODE','gpt-id',result='SCREEN_NEGATIVE'),
     row('gpt','GPT-NODE','gpt-id',error_category='FAIL_TRANSPORT'),
     row('gpt','GPT-NODE','gpt-id',route_confirmed=False),
     row('gpt','GPT-NODE','gpt-id',method='regionrestrictioncheck-sidecar-v8'),
 ]
 assert r.manual_region_blocked_names(rows,m) == {
     'gpt':['GPT-NODE'],'gemini':['GEMINI-NODE']}


def test_gemini_antigravity_region_failure_blocks_manual_but_not_gpt():
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[
     {'exact_node_id':'hk-id','exact_node_name':'🇭🇰香港-CloudCode'},
 ]}
 row=lambda service,method:{
     'service':service,'node':'🇭🇰香港-CloudCode','exact_node_id':'hk-id',
     'source_snapshot_id':'snap','source_hash':'hash','result':'FAIL',
     'method':method,'route_confirmed':True,
     'error_category':'FAIL_FORBIDDEN_LOCATION'}
 assert r.manual_region_blocked_names(
     [row('gemini','antigravity_inference')], m
 ) == {'gpt': [], 'gemini': ['🇭🇰香港-CloudCode']}
 assert r.manual_region_blocked_names(
     [row('gpt','antigravity_inference')], m
 ) == {'gpt': [], 'gemini': []}


def test_safe_functional_loader_preserves_actual_use_proof_booleans(tmp_path):
 payload={
     'schema_version':1,'service':'gpt','source_hash':'hash',
     'results':[{
         'exact_node_id':'id','exact_node_name':'NEW',
         'source_snapshot_id':'snap','source_hash':'hash',
         'tested_at':'2026-10-10T00:00:00+00:00',
         'probe_method_version':'desktop-web-route-marker-v1',
         'result':'PASS','marker_verified':True,'route_confirmed':False,
     }],
 }
 path=tmp_path/'functional.json';path.write_text(json.dumps(payload))
 loaded=s.load_functional_results([path])
 assert loaded[0]['marker_verified'] is True
 assert loaded[0]['route_confirmed'] is False


def test_restrict_ai_groups_preserves_valid_broad_manual_members():
 data={
  'proxies':[
   {'name':'jp'}, {'name':'🇭🇰香港'}, {'name':'us'}, {'name':'流媒体节点'},
  ],
  'proxy-groups':[
   {'name':'GPT专用','type':'select','proxies':['GPT手动','GPT候选','AI应急（未验证）']},
   {'name':'GPT手动','type':'select','proxies':['jp','🇭🇰香港','us','流媒体节点','stale','GPT候选','GPT历史LKG']},
   {'name':'GPT候选','type':'fallback','proxies':['us','stale']},
   {'name':'Gemini专用','type':'select','proxies':['Gemini手动','Gemini候选','AI应急（未验证）']},
   {'name':'Gemini手动','type':'select','proxies':['jp','🇭🇰香港','us','流媒体节点','stale','Gemini候选','Gemini历史LKG']},
   {'name':'Gemini候选','type':'fallback','proxies':['us','stale']},
   {'name':'GPT历史LKG','type':'fallback','proxies':['us']},
   {'name':'Gemini历史LKG','type':'fallback','proxies':['us']},
  ],
 }
 s.restrict_ai_group_members(data)
 groups={group['name']:group for group in data['proxy-groups']}
 assert groups['GPT候选']['proxies']==['us']
 assert groups['Gemini候选']['proxies']==['us']
 assert groups['GPT手动']['proxies']==['jp','us','流媒体节点','GPT候选']
 assert groups['Gemini手动']['proxies']==['jp','🇭🇰香港','us','流媒体节点','Gemini候选']

@pytest.mark.parametrize('kind',['rrc','disney'])
def test_subset_rejects_old_node_or_wrong_source(tmp_path,kind):
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[{'exact_node_id':'newid','exact_node_name':'NEW'},{'exact_node_id':'oldid','exact_node_name':'OLD'}]}
 p=tmp_path/'report.json';d=report(m,['OLD'],kind);p.write_text(json.dumps(d))
 with pytest.raises(s.ConfigError,match='SUBSET_MISMATCH'):r.validate_subset_report(s,p,m,['NEW'],kind)
 d=report(m,['NEW'],kind);d['source_hash']='wrong';p.write_text(json.dumps(d))
 with pytest.raises(s.ConfigError,match='BINDING'):r.validate_subset_report(s,p,m,['NEW'],kind)

def test_rrc_rejects_old_sentinel(tmp_path):
 m={'source_snapshot_id':'snap','source_hash':'hash','nodes':[{'exact_node_id':'id','exact_node_name':'NEW'}]};d=report(m,['NEW'],'rrc');d['systemic_gate_confirmations']=[{'sentinels':[{'sentinel_name':'OLD'}]}];p=tmp_path/'r.json';p.write_text(json.dumps(d))
 with pytest.raises(s.ConfigError,match='OLD_NODE_SENTINEL'):r.validate_subset_report(s,p,m,['NEW'],'rrc')

@pytest.mark.parametrize('added',[
    [],
    ['NEW1'],
    ['NEW1','NEW2'],
    ['🇸🇬新加坡-流媒体','🇯🇵日本-流媒体','🇭🇰香港'],
    ['eligible-a','🇯🇵日本-流媒体','eligible-b','Hong Kong node'],
])
def test_orchestration_tests_only_new_names_and_never_calls_old_sentinels(tmp_path,monkeypatch,added):
 events=[];source=tmp_path/'source.yaml';source.write_text('proxies: []\n');manifest_path=tmp_path/'manifest.json';manifest_path.write_text('{}')
 manifest={'source_snapshot_id':'snap','source_hash':'hash','nodes':[{'exact_node_id':'id-'+n,'exact_node_name':n} for n in ['OLD',*added]]}
 args=s.build_parser().parse_args(['update-candidate','--source-snapshot',str(manifest_path),'--workdir',str(tmp_path)])
 monkeypatch.setattr(s,'prepare_source_snapshot',lambda **kw:(events.append('freeze') or (manifest,source,{})))
 monkeypatch.setattr(r,'read_baseline',lambda *a:events.append('read_baseline') or 'proxies: []\n')
 monkeypatch.setattr(s,'restrict_ai_group_members',lambda d:None);monkeypatch.setattr(s,'validate_config',lambda d:None)
 monkeypatch.setattr(r,'measured_hk_baseline_names',lambda *a:set())
 helpers={'plan_nodes':lambda *a:{'added_names':added,'removed_names':[],'reused_names':['OLD'],'parameter_changed_names':['OLD']},'eligible_ai_rrc_names':u.eligible_ai_rrc_names,'build_candidate':lambda *a,**kw:({'proxies':[],'proxy-groups':[],'rules':[]},{'disney':kw['disney_pass_names']})}
 monkeypatch.setattr(r.runpy,'run_path',lambda *a:helpers)
 commands=[]
 def probe(cmd):
  commands.append(cmd);names=[]
  if cmd[1].endswith('regioncheck_service_probe.py'):
   names=[cmd[i+1] for i,x in enumerate(cmd) if x=='--node'];kind='rrc'
  else:
   ids=[cmd[i+1] for i,x in enumerate(cmd) if x=='--only-node-id'];names=[x['exact_node_name'] for x in manifest['nodes'] if x['exact_node_id'] in ids];kind='disney'
  expected = added if kind=='disney' else u.eligible_ai_rrc_names(added)
  assert names==expected
  Path(cmd[cmd.index('--output')+1]).write_text(json.dumps(report(manifest,names,kind)))
 monkeypatch.setattr(s,'run_probe_command',probe)
 result=r.run_incremental_update(args,s)
 assert events[:2]==['freeze','read_baseline']
 expected_rrc=u.eligible_ai_rrc_names(added)
 assert len(commands)==(0 if not added else 1 if len(expected_rrc)<2 else 2)
 expected_status = (
  'NO_ADDITIONS' if not added else
  'NO_AI_ELIGIBLE_ADDITIONS' if not expected_rrc else
  'NEEDS_ACTUAL_USE_VERIFICATION_SINGLE_NEW_NODE' if len(expected_rrc)==1 else
  'NEW_NAMES_SCREENED_NOT_ACTUAL_USE_VERIFIED'
 )
 assert result['rrc_status']==expected_status
 assert all('OLD' not in c and 'id-OLD' not in c for c in commands)
 assert result['old_node_service_tests']==0 and result['ai_new_names_admitted']=={'gpt':[],'gemini':[]}
 assert result['activated'] is False
 assert result['parameter_changed_names']==['OLD']

def test_concurrent_baseline_change_blocks_upload(tmp_path,monkeypatch):
 source=tmp_path/'s.yaml';source.write_text('proxies: []\n');m={'source_snapshot_id':'s','source_hash':'h','nodes':[]}
 args=s.build_parser().parse_args(['update-candidate','--source-snapshot',str(tmp_path/'m.json'),'--workdir',str(tmp_path),'--upload'])
 monkeypatch.setattr(s,'prepare_source_snapshot',lambda **kw:(m,source,{}));seq=iter(['proxies: []\n','proxies: []\n# changed\n']);monkeypatch.setattr(r,'read_baseline',lambda *a:next(seq));monkeypatch.setattr(r,'measured_hk_baseline_names',lambda *a:set());monkeypatch.setattr(s,'restrict_ai_group_members',lambda d:None);monkeypatch.setattr(s,'validate_config',lambda d:None)
 monkeypatch.setattr(r.runpy,'run_path',lambda *a:{'plan_nodes':lambda *a:{'added_names':[]},'eligible_ai_rrc_names':lambda names:names,'build_candidate':lambda *a,**k:({'proxies':[],'proxy-groups':[],'rules':[]},{})})
 monkeypatch.setattr(s,'upload_candidate',lambda *a,**k:pytest.fail('must not upload concurrent baseline'))
 with pytest.raises(s.ConfigError,match='BASELINE_CHANGED'):r.run_incremental_update(args,s)
