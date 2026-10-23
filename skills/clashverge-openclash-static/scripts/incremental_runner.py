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


def actual_use_admissions(functional_results, manifest, added_names, eligible_names):
    """Return only exact, current-snapshot browser proof for added AI names."""
    current_ids = {
        str(item.get('exact_node_name')): str(item.get('exact_node_id'))
        for item in manifest.get('nodes', [])
        if isinstance(item, dict)
    }
    snapshot_id = manifest.get('source_snapshot_id')
    source_hash = manifest.get('source_hash')
    added = set(added_names)
    eligible = set(eligible_names)
    admitted = {'gpt': set(), 'gemini': set()}
    for item in functional_results:
        if not isinstance(item, dict):
            continue
        service = item.get('service')
        if service not in admitted:
            continue
        name = item.get('node', item.get('exact_node_name'))
        node_id = item.get('exact_node_id')
        if not isinstance(name, str) or not isinstance(node_id, str):
            continue
        method_allowed = (
            item.get('method') == 'desktop-web-route-marker-v1'
            if service == 'gpt'
            else item.get('method') in {
                'desktop-web-route-marker-v1',
                'antigravity_inference',
            }
        )
        if (
            item.get('result') == 'PASS'
            and item.get('source_snapshot_id') == snapshot_id
            and item.get('source_hash') == source_hash
            and name in added
            and name in eligible
            and current_ids.get(name) == node_id
            and method_allowed
            and item.get('marker_verified') is True
            and item.get('route_confirmed') is True
        ):
            admitted[service].add(name)
    return {
        service: [name for name in added_names if name in names]
        for service, names in admitted.items()
    }


def manual_region_blocked_names(functional_results, manifest):
    """Return current-snapshot exact functional region blocks by service."""
    current_nodes = [
        item
        for item in manifest.get('nodes', [])
        if isinstance(item, dict)
        and isinstance(item.get('exact_node_name'), str)
        and isinstance(item.get('exact_node_id'), str)
    ]
    current_by_name = {
        item['exact_node_name']: item['exact_node_id'] for item in current_nodes
    }
    snapshot_id = manifest.get('source_snapshot_id')
    source_hash = manifest.get('source_hash')
    blocked = {'gpt': set(), 'gemini': set()}
    for item in functional_results:
        if not isinstance(item, dict):
            continue
        service = item.get('service')
        if service not in blocked:
            continue
        name = item.get('node', item.get('exact_node_name'))
        node_id = item.get('exact_node_id')
        method_allowed = (
            item.get('method') == 'desktop-web-route-marker-v1'
            if service == 'gpt'
            else item.get('method') in {
                'desktop-web-route-marker-v1',
                'antigravity_inference',
            }
        )
        if (
            not isinstance(name, str)
            or not isinstance(node_id, str)
            or current_by_name.get(name) != node_id
            or item.get('source_snapshot_id') != snapshot_id
            or item.get('source_hash') != source_hash
            or item.get('result') != 'FAIL'
            or item.get('route_confirmed') is not True
            or not method_allowed
            or item.get('error_category')
            not in {'FAIL_REGION', 'FAIL_FORBIDDEN_LOCATION'}
        ):
            continue
        blocked[service].add(name)
    return {
        service: [
            item['exact_node_name']
            for item in current_nodes
            if item['exact_node_name'] in names
        ]
        for service, names in blocked.items()
    }


def verified_registry_preferred_names(skill, source_data, identity_key_path):
    """Return current-source names matched to enabled preferred registry IDs.

    The converter's registry context binds entries by the stable connection
    identity HMAC.  Name-only records, removed nodes, and changed-identity
    same-name nodes therefore never enter the incremental candidate seed.
    """

    empty = {'gpt': [], 'gemini': []}
    build_context = getattr(skill, 'build_verified_service_registry_context', None)
    resolve_path = getattr(skill, 'verified_service_registry_path', None)
    proxy_loader = getattr(skill, 'static_proxy_objects', None)
    if build_context is None or resolve_path is None or proxy_loader is None:
        return empty
    if not isinstance(source_data.get('proxies'), list) or not source_data['proxies']:
        return empty
    registry_path = Path(resolve_path())
    if not registry_path.is_file():
        return empty
    proxies = proxy_loader(source_data)
    context = build_context(
        proxies,
        registry_path=registry_path,
        identity_key_path=identity_key_path,
    )
    if context is None:
        return empty
    source_names = [str(proxy['name']) for proxy in proxies]
    preferred_order = context.get('preferred_order', {})
    return {
        service: [
            name
            for name in source_names
            if name in set(preferred_order.get(service, ()))
        ]
        for service in ('gpt', 'gemini')
    }


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
    registry_preferred = verified_registry_preferred_names(
        skill, new, args.source_identity_key
    )
    eligible_ai_names = helpers['eligible_ai_rrc_names'](names)
    registry_names = set(registry_preferred['gpt']) | set(
        registry_preferred['gemini']
    )
    rrc_names = [
        name
        for name in eligible_ai_names
        if name not in registry_names
    ]
    functional_results = skill.load_functional_results(
        getattr(args, 'functional_results', ())
    )
    verified_ai_names = actual_use_admissions(
        functional_results, manifest, names, eligible_ai_names
    )
    region_blocked_names = manual_region_blocked_names(
        functional_results, manifest
    )
    report_path = directory / 'incremental-report.json'
    report = {'schema_version': 1, 'skill_version': skill.SKILL_VERSION,
              'source_snapshot_id': manifest['source_snapshot_id'], 'source_hash': manifest['source_hash'],
              'baseline_sha256': baseline_hash, **plan, 'old_node_service_tests': 0,
              'started_at': skill.iso_now(), 'status': 'PREPARING',
              'service_probe_names': names,
              'ai_new_names_admitted': {'gpt': [], 'gemini': []},
              'registry_preferred_names': registry_preferred,
              'manual_region_blocked_names': region_blocked_names,
              'ai_evidence_policy': 'carry existing curated membership by name; admit added GPT names only from current-snapshot desktop-web-route-marker-v1 proof and Gemini names from current-snapshot desktop-web-route-marker-v1 or antigravity_inference proof; screening cannot admit new AI nodes; exclude only exact current-snapshot service-specific region failures from the matching service'}
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
                report['rrc_status'] = (
                    'NO_UNVERIFIED_AI_ADDITIONS'
                    if registry_names.intersection(eligible_ai_names)
                    else 'NO_AI_ELIGIBLE_ADDITIONS'
                )
            else:
                report['rrc_status'] = 'NEEDS_ACTUAL_USE_VERIFICATION_SINGLE_NEW_NODE'
        disney_pass = [name for name in names if skill.is_disney_region_name(name)]
        report['disney_policy'] = 'POLICY_STATIC_REGIONS_NO_PROBE'
        hk_names = measured_hk_baseline_names(skill, old, args.source_identity_key)
        candidate, selection_report = helpers['build_candidate'](
            old,
            new,
            skill,
            disney_pass_names=disney_pass,
            measured_hk_names=hk_names,
            verified_gpt_names=set(verified_ai_names['gpt']),
            verified_gemini_names=set(verified_ai_names['gemini']),
            registry_gpt_names=registry_preferred['gpt'],
            registry_gemini_names=registry_preferred['gemini'],
            blocked_gpt_names=set(region_blocked_names['gpt']),
            blocked_gemini_names=set(region_blocked_names['gemini']),
        )
        skill.restrict_ai_group_members(candidate)
        skill.validate_config(candidate)
        output = directory / 'openclash-incremental.yaml'
        skill.dump_yaml(candidate, output); output.chmod(0o600)
        audit = directory / 'openclash-incremental-audit.yaml'
        skill.dump_yaml(skill.make_audit_copy(candidate), audit); audit.chmod(0o600)
        report['selection'] = selection_report
        admitted_report = selection_report.get(
            'ai_new_names_admitted',
            {
                'gpt': selection_report.get('admitted_gpt_names', verified_ai_names['gpt']),
                'gemini': selection_report.get('admitted_gemini_names', verified_ai_names['gemini']),
            },
        )
        report['ai_new_names_admitted'] = {
            'gpt': list(admitted_report.get('gpt', ())),
            'gemini': list(admitted_report.get('gemini', ())),
        }
        report['measured_hk_exclusions'] = sorted(hk_names)
        report['manual_region_blocked_names'] = selection_report.get(
            'manual_region_blocked_names', region_blocked_names
        )
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
