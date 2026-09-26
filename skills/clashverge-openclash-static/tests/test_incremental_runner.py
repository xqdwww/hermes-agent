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
 assert result['old_node_service_tests']==0 and result['ai_new_names_admitted']==[]
 assert result['activated'] is False
 assert result['parameter_changed_names']==['OLD']

def test_concurrent_baseline_change_blocks_upload(tmp_path,monkeypatch):
 source=tmp_path/'s.yaml';source.write_text('proxies: []\n');m={'source_snapshot_id':'s','source_hash':'h','nodes':[]}
 args=s.build_parser().parse_args(['update-candidate','--source-snapshot',str(tmp_path/'m.json'),'--workdir',str(tmp_path),'--upload'])
 monkeypatch.setattr(s,'prepare_source_snapshot',lambda **kw:(m,source,{}));seq=iter(['proxies: []\n','proxies: []\n# changed\n']);monkeypatch.setattr(r,'read_baseline',lambda *a:next(seq));monkeypatch.setattr(r,'measured_hk_baseline_names',lambda *a:set());monkeypatch.setattr(s,'restrict_ai_group_members',lambda d:None);monkeypatch.setattr(s,'validate_config',lambda d:None)
 monkeypatch.setattr(r.runpy,'run_path',lambda *a:{'plan_nodes':lambda *a:{'added_names':[]},'eligible_ai_rrc_names':lambda names:names,'build_candidate':lambda *a,**k:({'proxies':[],'proxy-groups':[],'rules':[]},{})})
 monkeypatch.setattr(s,'upload_candidate',lambda *a,**k:pytest.fail('must not upload concurrent baseline'))
 with pytest.raises(s.ConfigError,match='BASELINE_CHANGED'):r.run_incremental_update(args,s)
