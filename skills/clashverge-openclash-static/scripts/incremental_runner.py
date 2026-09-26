"""Exact-name update orchestration; evidence is never rebound as fresh proof."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys


def read_baseline(skill, host):
    result = skill.ssh_command(host, 'set -e; p=$(uci -q get openclash.config.config_path); test -n "$p"; test -f "$p"; cat "$p"', capture=True)
    return result.stdout


def validate_subset_report(skill, path, manifest, names, kind):
    report = skill.load_json_object(path)
    expected = {x['exact_node_id']: x['exact_node_name'] for x in manifest['nodes'] if x['exact_node_name'] in names}
    if (report.get('source_snapshot_id') != manifest['source_snapshot_id'] or report.get('source_hash') != manifest['source_hash'] or report.get('production_fingerprint_preserved') is not True):
        raise skill.ConfigError('INCREMENTAL_PROBE_BINDING_OR_PRODUCTION_MISMATCH')
    rows = report.get('node_attempts' if kind == 'rrc' else 'nodes')
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise skill.ConfigError('INCREMENTAL_PROBE_SUBSET_INCOMPLETE')
    actual = {r.get('exact_node_id'): r.get('exact_node_name') for r in rows}
    if actual != expected or any(r.get('source_snapshot_id') != manifest['source_snapshot_id'] for r in rows):
        raise skill.ConfigError('INCREMENTAL_PROBE_SUBSET_MISMATCH')
    if kind == 'rrc':
        if report.get('status') != 'COMPLETE' or report.get('attribution_mismatch') != 0 or report.get('auto_calibration_status') != 'PASS_RRC_PROXY_ATTRIBUTION_TWO_NODE_AUTO_CALIBRATION':
            raise skill.ConfigError('INCREMENTAL_RRC_NOT_COMPLETE')
        for r in report.get('results', []):
            if expected.get(r.get('exact_node_id')) != r.get('exact_node_name') or r.get('source_hash') != manifest['source_hash'] or r.get('source_snapshot_id') != manifest['source_snapshot_id']:
                raise skill.ConfigError('INCREMENTAL_RRC_RESULT_BINDING_MISMATCH')
        for confirmation in report.get('systemic_gate_confirmations', []):
            if any(r.get('sentinel_name') not in names for r in confirmation.get('sentinels', [])):
                raise skill.ConfigError('INCREMENTAL_OLD_NODE_SENTINEL_FORBIDDEN')
    elif any(r.get('source_hash') != manifest['source_hash'] for r in rows):
        raise skill.ConfigError('INCREMENTAL_DISNEY_RESULT_BINDING_MISMATCH')
    return report


def measured_hk_baseline_names(skill, old, identity_key_path):
    path = skill.DEFAULT_PROBE_ARTIFACT_CACHE_DIR / 'latest-regioncheck.json'
    if not path.is_file():
        return set()
    cache = skill.load_json_object(path)
    if cache.get('production_fingerprint_preserved') is not True:
        return set()
    key = identity_key_path.expanduser().read_bytes()
    ids = {skill.stable_node_identity(p, key): p['name'] for p in skill.static_proxy_objects(old)}
    return {ids[r['exact_node_id']] for r in cache.get('results', [])
            if r.get('exact_node_id') in ids and r.get('attribution_status') == 'ATTRIBUTION_MATCH'
            and str(r.get('exit_country', '')).upper().replace(' ', '') in {'HK', 'HKG', 'HONGKONG'}}


def run_incremental_update(args, skill):
    if not 0 < args.min_node_retention_ratio <= 1:
        raise skill.ConfigError('--min-node-retention-ratio must be in (0, 1].')
    manifest, source, runtime = skill.prepare_source_snapshot(
        source=args.source, workdir=args.workdir, refresh_adapter=args.refresh_adapter,
        no_refresh=args.no_refresh_source, source_snapshot=args.source_snapshot,
        identity_key_path=args.source_identity_key, refresh_timeout=args.refresh_timeout,
        min_node_retention_ratio=args.min_node_retention_ratio)
    manifest_path = Path(runtime.get('manifest_path') or args.source_snapshot).resolve()
    directory = args.workdir.expanduser().resolve() / ('incremental-' + manifest['source_snapshot_id'])
    directory.mkdir(parents=True, exist_ok=True); directory.chmod(0o700)
    old_text = read_baseline(skill, args.host)
    baseline_hash = hashlib.sha256(old_text.encode()).hexdigest()
    baseline_file = directory / 'production-baseline.private.yaml'
    baseline_file.write_text(old_text); baseline_file.chmod(0o600)
    old = skill.load_yaml(baseline_file)
    new = skill.load_yaml(source)
    helpers = runpy.run_path(str(Path(__file__).with_name('incremental_update.py')))
    plan = helpers['plan_nodes'](old, new, skill)
    names = plan['added_names']
    rrc_names = helpers['eligible_ai_rrc_names'](names)
    report_path = directory / 'incremental-report.json'
    report = {'schema_version': 1, 'skill_version': skill.SKILL_VERSION,
              'source_snapshot_id': manifest['source_snapshot_id'], 'source_hash': manifest['source_hash'],
              'baseline_sha256': baseline_hash, **plan, 'old_node_service_tests': 0,
              'started_at': skill.iso_now(), 'status': 'PREPARING',
              'service_probe_names': names, 'ai_new_names_admitted': [],
              'ai_evidence_policy': 'carry existing curated membership by name; not fresh actual-use proof; screening cannot admit new AI nodes'}
    skill.atomic_write_json(report, report_path, private_parent=True)
    disney_pass = []
    script_dir = Path(skill.__file__).parent
    try:
        if len(rrc_names) >= 2:
            rrc_path = directory / 'added-regioncheck.json'
            if not rrc_path.exists():
                command = [sys.executable, str(script_dir / 'regioncheck_service_probe.py'), '--skill-script', str(Path(skill.__file__).resolve()), '--source-snapshot', str(manifest_path), '--output', str(rrc_path), '--host', args.host, '--core-path', args.core_path, '--timeout', str(args.rrc_timeout), '--node-interval', str(args.rrc_node_interval), '--auto-calibrate']
                for name in rrc_names:
                    command.extend(['--node', name])
                skill.run_probe_command(command)
            validate_subset_report(skill, rrc_path, manifest, rrc_names, 'rrc')
            report['rrc_status'] = 'NEW_NAMES_SCREENED_NOT_ACTUAL_USE_VERIFIED'
        else:
            if not names:
                report['rrc_status'] = 'NO_ADDITIONS'
            elif not rrc_names:
                report['rrc_status'] = 'NO_AI_ELIGIBLE_ADDITIONS'
            else:
                report['rrc_status'] = 'NEEDS_ACTUAL_USE_VERIFICATION_SINGLE_NEW_NODE'
        if names:
            disney_path = directory / 'added-disney.json'
            if not disney_path.exists():
                command = [sys.executable, str(script_dir / 'disney_service_probe.py'), '--skill-script', str(Path(skill.__file__).resolve()), '--source-snapshot', str(manifest_path), '--output', str(disney_path), '--host', args.host, '--core-path', args.core_path]
                for item in manifest['nodes']:
                    if item['exact_node_name'] in names:
                        command.extend(['--only-node-id', item['exact_node_id']])
                skill.run_probe_command(command)
            disney = validate_subset_report(skill, disney_path, manifest, names, 'disney')
            disney_pass = [r['exact_node_name'] for r in disney['nodes'] if r.get('result') == 'PASS_SUPPORTED_REGION']
        hk_names = measured_hk_baseline_names(skill, old, args.source_identity_key)
        candidate, selection_report = helpers['build_candidate'](old, new, skill, disney_pass_names=disney_pass, measured_hk_names=hk_names)
        skill.restrict_ai_group_members(candidate)
        skill.validate_config(candidate)
        output = directory / 'openclash-incremental.yaml'
        skill.dump_yaml(candidate, output); output.chmod(0o600)
        audit = directory / 'openclash-incremental-audit.yaml'
        skill.dump_yaml(skill.make_audit_copy(candidate), audit); audit.chmod(0o600)
        report['selection'] = selection_report
        report['measured_hk_exclusions'] = sorted(hk_names)
        report['candidate_sha256'] = skill.sha256_file(output)
        report['candidate_path'] = str(output)
        if read_baseline(skill, args.host) != old_text:
            raise skill.ConfigError('INCREMENTAL_PRODUCTION_BASELINE_CHANGED')
        uploaded = None
        if args.upload:
            uploaded = skill.upload_candidate(output, host=args.host, remote_name=args.remote_name, core_path=args.core_path)
            skill.probe_uploaded_candidate(output, host=args.host, core_path=args.core_path, candidate_path=uploaded.candidate_path)
        report['status'] = 'READY_FOR_EXPLICIT_ACTIVATE_APPROVAL' if uploaded else 'CANDIDATE_GENERATED_NOT_UPLOADED'
        report['remote_candidate_path'] = uploaded.candidate_path if uploaded else None
        report['completed_at'] = skill.iso_now()
        report['activated'] = False
        skill.atomic_write_json(report, report_path, private_parent=True)
        return {**report, 'formal_update_journal_path': str(report_path)}
    except BaseException:
        report['status'] = 'FAILED_SAFE_PRODUCTION_NOT_ACTIVATED'
        skill.atomic_write_json(report, report_path, private_parent=True)
        raise
