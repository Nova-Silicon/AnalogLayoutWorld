"""Private source-suite support for waveform and cross-analysis SPEC checks.

A task adapter declares the complete analysis plan and evaluates frozen source
predicates. The generic
runner supplies the trusted DUT/model paths and retains the native simulation
evidence. No Agent code is executed by this runner.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

from .simulation import (ordered_deck_runs, recheck_failed_analysis,
                         solver_recheck_summary, primary_analysis_checkpoint,
                         completed_solver_recheck, sparse_recheck_arguments)
from .simulation_progress import NativeExecutionReceipts, atomic_json

SOLVER_RECORD_FIELDS = ('solver_attempts', 'solver_disagreement', 'adopted_solver', 'solver_recheck')


def retain_analysis_row(record, row):
    """Keep invalid numeric evidence JSON-safe and outside the scored row."""
    nonfinite = []

    def evidence(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            token = str(value)
            nonfinite.append({'path': path, 'value': token})
            return {'nonfinite_float': token}
        if isinstance(value, dict):
            return {key: evidence(item, path + [key]) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [evidence(item, path + [index]) for index, item in enumerate(value)]
        return value

    saved = evidence(row, [])
    json.dumps(saved, allow_nan=False)
    if nonfinite:
        record.update(row=None, invalid_row=saved, nonfinite_measurements=nonfinite,
                      error='ValueError: Nonfinite source measurements: ' +
                      ', '.join('.'.join(map(str, item['path'])) for item in nonfinite))
    else:
        record['row'] = row


def load_adapter(task: Path, settings: dict, *, reference: bool = False):
    root = (task / 'testbench').resolve(strict=True)
    path = (root / settings['suite']).resolve(strict=True)
    if not path.is_relative_to(root) or path.suffix != '.py':
        raise ValueError('Suite must be a Python module under the trusted testbench')
    spec = importlib.util.spec_from_file_location('alb_private_suite', path)
    module = importlib.util.module_from_spec(spec)
    # No public workspace or submission path is used for imports.
    sys.path.insert(0, str(root))
    try:
        spec.loader.exec_module(module)
        adapter = module.create_suite(root, reference=reference)
    finally:
        sys.path.pop(0)
    for method in ('plan', 'deck', 'analyze', 'checks'):
        if not callable(getattr(adapter, method, None)):
            raise ValueError(f'Suite lacks {method}()')
    validate_plan(adapter.plan())
    return adapter


def validate_plan(plan: list[dict]) -> None:
    if not isinstance(plan, list) or not plan:
        raise ValueError('Suite plan must be a nonempty list')
    ids = set()
    for case in plan:
        for field in ('id', 'score_group'):
            if not isinstance(case.get(field), str) or not case[field]:
                raise ValueError(f'Every analysis needs a nonempty {field}')
        if case['id'] in ids:
            raise ValueError(f'Duplicate analysis ID: {case["id"]}')
        ids.add(case['id'])


def evaluation_plan(plan: list[dict], case_ids: list[str] | None = None) -> list[dict]:
    """Select explicitly named analyses without changing their source definitions.

    An absent selector preserves the historical complete plan. An explicit
    selector must be nonempty and exact; typos must not silently reduce coverage.
    Source order is retained so independent profile filters keep their semantics.
    """
    if case_ids is None:
        return plan
    if (not isinstance(case_ids, list) or not case_ids
            or any(not isinstance(key, str) or not key for key in case_ids)):
        raise ValueError('evaluation_case_ids must be a nonempty list of analysis IDs')
    if len(set(case_ids)) != len(case_ids):
        raise ValueError('Duplicate evaluation_case_ids')
    available = {case['id'] for case in plan}
    unknown = set(case_ids) - available
    if unknown:
        raise ValueError(f'Unknown evaluation_case_ids: {sorted(unknown)}')
    selected = set(case_ids)
    return [case for case in plan if case['id'] in selected]


def dependency_plan(adapter, source_plan: list[dict], selected: list[dict]):
    """Order trusted analysis dependencies without adding scoring conditions.

    Dependencies identify unchanged cases in the original source plan. They
    supply measurements to the analyzer; only ``selected`` remains scored.
    Adapters without the optional hook retain their original execution order.
    """
    declare = getattr(adapter, 'analysis_dependencies', None)
    if declare is not None and not callable(declare):
        raise ValueError('analysis_dependencies must be callable')
    available = {case['id']: case for case in source_plan}
    dependencies, ordered, active, finished = {}, [], set(), set()

    def visit(ident):
        if ident in finished:
            return
        if ident in active:
            raise ValueError(f'Cyclic analysis dependency: {ident}')
        if ident not in available:
            raise ValueError(f'Unknown analysis dependency: {ident}')
        case = available[ident]
        required = [] if declare is None else declare(case)
        if (not isinstance(required, list)
                or any(not isinstance(key, str) or not key for key in required)):
            raise ValueError('analysis_dependencies must return a list of analysis IDs')
        if len(set(required)) != len(required):
            raise ValueError(f'Duplicate analysis dependencies: {ident}')
        dependencies[ident] = required
        active.add(ident)
        for key in required:
            visit(key)
        active.remove(ident)
        finished.add(ident)
        ordered.append(case)

    for case in selected:
        visit(case['id'])
    return ordered, dependencies


def coverage(source_plan: list[dict], plan: list[dict]) -> dict:
    selected = {case['id'] for case in plan}
    return {
        'source_analysis_count': len(source_plan),
        'evaluation_analysis_count': len(plan),
        'evaluation_case_ids': [case['id'] for case in plan],
        'excluded_case_ids': [case['id'] for case in source_plan if case['id'] not in selected],
    }


def selected_reducer(adapter, plan: list[dict]):
    """Require an explicit adapter for cross-analysis predicates on a subset."""
    subset = {case['id'] for case in plan} != {case['id'] for case in adapter.plan()}
    if subset:
        reducer = getattr(adapter, 'reduce_selected', None)
        if hasattr(adapter, 'reduce_suite') and not callable(reducer):
            raise ValueError('Selected evaluation requires reduce_selected(records, report, plan)')
        return reducer, subset
    return getattr(adapter, 'reduce_suite', None), subset


def expected_groups(plan: list[dict]) -> dict:
    validate_plan(plan)
    # This is an explicitly Boolean source-check result, not a fabricated
    # physical measurement. Its detailed predicates/values stay in the report.
    return {case['score_group']: {'source_checks': {'min': 1, 'max': 1,
                                                   'unit': 'boolean'}}
            for case in plan}


def case_checks(check_case, case: dict, record: dict | None) -> tuple[str | None, list]:
    """Evaluate one analysis record against its frozen source predicates."""
    error, checks = None, []
    if record is None:
        error = 'missing analysis'
    elif record.get('error'):
        error = record['error']
    elif json.dumps(record.get('case'), sort_keys=True, allow_nan=False) != json.dumps(case, sort_keys=True, allow_nan=False):
        error = 'record does not identify the requested analysis'
    elif record.get('run', {}).get('returncode') != 0:
        error = 'ngspice did not exit successfully'
    else:
        try:
            checks = check_case(case, record['row'])
            if not isinstance(checks, list) or not checks:
                raise ValueError('No required source predicates returned')
            names = []
            for check in checks:
                if not isinstance(check.get('name'), str) or not check['name']:
                    raise ValueError('Source predicate needs a name')
                if type(check.get('passed')) is not bool:
                    raise ValueError('Source predicate must return a Boolean')
                names.append(check['name'])
            if len(set(names)) != len(names):
                raise ValueError('Duplicate source predicate names')
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
    return error, checks


def case_outcome(check_case, case: dict, record: dict) -> dict:
    """Per-analysis verdict used to decide a solver recheck.

    aggregate() remains the authoritative scorer; this applies the same
    per-analysis predicates without suite-level reduction.
    """
    error, checks = case_checks(check_case, case, record)
    passed = error is None and all(check['passed'] for check in checks)
    detail = {'row': record.get('row'), 'checks': checks}
    if 'invalid_row' in record:
        detail['invalid_row'] = record['invalid_row']
    return {'passed': bool(passed), 'payload': record, 'detail': detail, 'evidence': {
        'verdict': 'passed' if passed else 'error' if error else 'failed',
        'passed': bool(passed), 'error': error,
        'failed_checks': [] if error else [check['name'] for check in checks if not check['passed']]}}


def aggregate(adapter, records: list[dict], *, plan: list[dict] | None = None) -> dict:
    plan = adapter.plan() if plan is None else plan
    validate_plan(plan)
    reducer, subset = selected_reducer(adapter, plan)
    check_case = getattr(adapter, 'checks_selected', adapter.checks) if subset else adapter.checks
    expected = {case['id']: case for case in plan}
    ids = [record.get('case_id') for record in records]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    unknown = [key for key in ids if key not in expected]
    integrity = []
    if duplicates:
        integrity.append(f'duplicate analysis IDs: {duplicates}')
    if unknown:
        integrity.append(f'unexpected analysis IDs: {unknown}')
    indexed = {record.get('case_id'): record for record in records}
    analyses, groups = {}, {}
    for case in plan:
        record = indexed.get(case['id'])
        error, checks = case_checks(check_case, case, record)
        passed = not integrity and error is None and all(check['passed'] for check in checks)
        analyses[case['id']] = {'passed': bool(passed), 'error': error, 'checks': checks,
                                'row': record.get('row') if record else None}
        if record and 'invalid_row' in record:
            analyses[case['id']].update(invalid_row=record['invalid_row'],
                                      nonfinite_measurements=record['nonfinite_measurements'])
        if record:
            analyses[case['id']].update({key: record[key] for key in SOLVER_RECORD_FIELDS
                                         if key in record})
        groups.setdefault(case['score_group'], []).append(case['id'])
    report = {'required_analysis_count': len(plan), 'recorded_analysis_count': len(records),
              'required_group_count': len(groups), 'integrity_errors': integrity,
              'unassessed_requirements': [],
              'case_results': analyses,
              'group_results': {name: {'passed': all(analyses[key]['passed'] for key in keys),
                                       'required_case_ids': keys}
                                for name, keys in groups.items()}}
    before = {name: value['passed'] for name, value in report['group_results'].items()}
    if reducer is not None:
        try:
            report = reducer(records, report, plan) if subset else reducer(records, report)
            if set(report['group_results']) != set(groups):
                raise ValueError('Suite reducer changed the fixed group set')
            for name, value in report['group_results'].items():
                if type(value.get('passed')) is not bool:
                    raise ValueError('Suite reducer must return Boolean group results')
                if value['passed'] and not before[name]:
                    raise ValueError('Suite reducer revived an incomplete or failed group')
        except Exception as exc:
            report['integrity_errors'].append(f'suite reduction error: {type(exc).__name__}: {exc}')
            report['group_results'] = {name: {'passed': False, 'required_case_ids': keys}
                                       for name, keys in groups.items()}
    report['passed_group_count'] = sum(row['passed'] for row in report['group_results'].values())
    return report


def scoring_cases(report: dict) -> dict:
    results = {}
    for group, row in report['group_results'].items():
        complete = not report['integrity_errors'] and all(
            report['case_results'][key]['error'] is None for key in row['required_case_ids'])
        value = int(row['passed']) if complete else None
        results[group] = {
            'status': 'passed' if row['passed'] else 'failed' if complete else 'incomplete',
            'passed': row['passed'], 'source_case_ids': row['required_case_ids'],
            'measurements': {'source_checks': {
                'value': value, 'status': 'measured' if complete else 'missing_or_invalid',
                'passed': row['passed'], 'limits': {'min': 1, 'max': 1, 'unit': 'boolean'},
            }},
        }
    return results


def simulate(adapter, dut: Path, model: Path, out: Path, timeout: float,
             *, profile: str, run_deck,
             initialization: str = "set num_threads=1\n", workers: int = 1,
             cpu_budget: int | None = None,
             evaluation_case_ids: list[str] | None = None,
             solver_recheck: bool = False,
             execution_metadata: dict | None = None) -> dict:
    """Run the suite plan; ``solver_recheck`` enables the post-layout
    KLU-failure SPARSE recheck (eda.simulation.recheck_failed_analysis).

    Trusted execution metadata adds independent provenance fields to both
    returned and progress results, including before the first case completes.
    It cannot replace suite, resource, analysis or scoring result fields.
    """
    from .simulation_resources import positive_integer, simulation_resources, configure_deck_threads
    positive_integer(workers, 'Simulation workers')
    if cpu_budget is not None:
        positive_integer(cpu_budget, 'Simulation CPU budget')
    if not isinstance(initialization, str):
        raise ValueError('Private suite initialization must be a string')
    if profile not in {'full', 'tt'}:
        raise ValueError('Unsupported suite profile')
    if type(solver_recheck) is not bool:
        raise ValueError('solver_recheck must be a Boolean')
    if execution_metadata is not None and not isinstance(execution_metadata, dict):
        raise ValueError('Suite execution_metadata must be an object or None')
    metadata = deepcopy(execution_metadata) if execution_metadata is not None else {}
    if any(not isinstance(key, str) or not key for key in metadata):
        raise ValueError('Suite execution_metadata keys must be nonempty strings')
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('Suite execution_metadata must contain finite JSON data') from error
    source_plan = adapter.plan()
    validate_plan(source_plan)
    plan = evaluation_plan(source_plan, evaluation_case_ids)
    _, subset = selected_reducer(adapter, plan)
    selected_checks = getattr(adapter, 'checks_selected', adapter.checks) if subset else adapter.checks
    scope = coverage(source_plan, plan)
    # Native diagnostic coverage is declared explicitly by the adapter; never
    # infer nominal voltage/temperature from the name of a task.
    selected = plan if profile == 'full' else [c for c in plan if c.get('profile') == 'tt']
    if not selected:
        raise ValueError('Suite declares no cases for the requested profile')
    execution_plan, dependencies = dependency_plan(adapter, source_plan, selected)
    selected_ids = {case['id'] for case in selected}
    auxiliary_ids = [case['id'] for case in execution_plan if case['id'] not in selected_ids]
    scope['auxiliary_case_ids'] = auxiliary_ids
    resources = simulation_resources(workers, len(execution_plan), cpu_budget)
    records, executions, all_records = [], [], {}
    result = {'status': 'running', 'profile': profile,
              'scope': ('selected_evaluation' if scope['excluded_case_ids'] else 'full')
                       if profile == 'full' else 'diagnostic',
              'coverage': scope,
              'expected_case_ids': list(expected_groups(plan)), 'required_case_count': len(expected_groups(plan)),
              'input_netlist': str(dut), 'model_lib': str(model),
              'initialization': initialization,
              **resources.record()}
    # These result fields are populated after analysis; they are reserved now
    # so metadata cannot masquerade as a result before they are available.
    result_fields = set(result) | {
        'case_results', 'source_evidence', 'runs', 'auxiliary_results',
        'solver_recheck', 'solver_disagreement', 'passed_case_count',
        'measurements_complete', 'evaluation_fully_measured', 'evaluation_passed',
        'original_spec_fully_measured', 'original_spec_passed',
        'all_requested_passed', 'error_kind',
    }
    conflicts = set(metadata) & result_fields
    if conflicts:
        raise ValueError('Suite execution_metadata cannot override result fields: '
                         + ', '.join(sorted(conflicts)))
    result.update(metadata)
    # An external verifier deadline can interrupt the very first native case.
    # Persist the expected denominator and execution provenance beforehand.
    atomic_json(out / 'metrics.json', result)
    prepared = []
    receipts = NativeExecutionReceipts(run_deck)

    def requests():
        for index, case in enumerate(execution_plan):
            work = out / f'case_{index:04d}'
            work.mkdir()
            deck, raw = adapter.deck(case, dut, model)
            if not isinstance(deck, str) or not deck.strip() or type(raw) is not bool:
                raise ValueError('Suite deck() must return nonempty SPICE and a Boolean raw-output flag')
            thread_changes = []
            if resources.threads_per_worker is not None:
                deck, thread_changes = configure_deck_threads(deck, resources.threads_per_worker)
            path = work / 'testbench.spi'
            path.write_text(deck)
            options = {'deck': path, 'out': work, 'timeout': timeout,
                       'initialization': initialization,
                       'raw_output': work / 'analysis.raw' if raw else None}
            if resources.threads_per_worker is not None:
                options['num_threads'] = resources.threads_per_worker
            context = (case, work, thread_changes, options)
            prepared.append(context)
            yield context, options

    unpublished_analyses = set()
    unavailable_state = set()

    def analysis_record(case, work, execution, analyzed):
        # Keep the source analyzer's conventional log name, without another run.
        log = Path(execution['command']['log_path'])
        (work / 'ngspice.log').write_bytes(log.read_bytes())
        run = {'returncode': execution['command']['returncode'],
               'wall_seconds': execution['command']['seconds'], 'command': execution['command']}
        record = {'case_id': case['id'], 'case': case, 'run': run, 'row': None, 'error': None}
        if execution['status'] == 'completed':
            try:
                unavailable = [key for key in dependencies[case['id']]
                               if key not in all_records or all_records[key].get('error')
                               or all_records[key].get('row') is None
                               or all_records[key]['run']['returncode'] != 0]
                if unavailable:
                    raise ValueError('Dependency analysis unavailable: ' + ', '.join(unavailable))
                analyzed.append(work)
                unpublished_analyses.add(case['id'])
                retain_analysis_row(record, adapter.analyze(case, work, run))
            except Exception as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                record['row'] = None
        else:
            record['error'] = execution.get('error_kind', 'execution_error')
        return record

    # Analyses whose analyze() state can feed a later dependent analysis.
    prerequisite_ids = {key for required in dependencies.values() for key in required}
    recheck_infos = {}
    run_entries = {}
    primary_outcomes = {}

    def publish(context, outcome, run_entry):
        nonlocal records, executions, report
        case, work, _, _ = context
        record = outcome['payload']
        all_records[case['id']] = record
        run_entries[case['id']] = run_entry
        records = [all_records[c['id']] for c in execution_plan
                   if c['id'] in selected_ids and c['id'] in all_records]
        executions = [run_entries[c['id']] for c in execution_plan if c['id'] in run_entries]
        atomic_json(work / 'result.json', record)
        report = aggregate(adapter, records, plan=plan)
        result.update(case_results=scoring_cases(report), source_evidence=report, runs=executions,
                      auxiliary_results=[all_records[key] for key in auxiliary_ids if key in all_records])
        if solver_recheck:
            summary = solver_recheck_summary(recheck_infos)
            result.update(solver_recheck=summary,
                          solver_disagreement=bool(summary['disagreement_case_ids']))
        atomic_json(out / 'metrics.json', result)
        unpublished_analyses.discard(case['id'])

    def primary(context, execution):
        case, work, thread_changes, options = context
        checks = selected_checks if case['id'] in selected_ids else adapter.checks
        analyzed = []

        def judge(run_execution, directory):
            run_execution['thread_configuration_changes'] = thread_changes
            record = analysis_record(case, directory, run_execution, analyzed)
            if directory != work:
                atomic_json(directory / 'result.json', record)
            return case_outcome(checks, case, record)

        outcome = judge(execution, work)
        primary_outcomes[case['id']] = (execution, outcome)
        run_entry = {'case_id': case['id'], 'auxiliary': case['id'] in auxiliary_ids, **execution}
        if solver_recheck:
            info = primary_analysis_checkpoint(options, execution, outcome)
            outcome['payload'].update(info)
            recheck_infos[case['id']] = info
            run_entry['adopted_solver'] = info['adopted_solver']
        publish(context, outcome, run_entry)
        return outcome, run_entry, judge, analyzed

    report = None
    try:
        with ordered_deck_runs(requests(), receipts, resources.workers) as completed:
            for context, execution in completed:
                case, work, thread_changes, options = context
                outcome, run_entry, judge, analyzed = primary(context, execution)
                if (solver_recheck and recheck_infos[case['id']]['solver_recheck']['status'] == 'pending'):
                    primary_record = outcome['payload']
                    try:
                        outcome, info, recheck_execution = recheck_failed_analysis(
                            receipts, options, execution, outcome, judge)
                    except BaseException as interruption:
                        # A recheck analyzer can update prerequisite state. An
                        # interrupted retry must not leak it to dependent rows.
                        if (case['id'] in prerequisite_ids and len(analyzed) > 1
                                and primary_record.get('row') is not None):
                            try:
                                adapter.analyze(case, work, primary_record['run'])
                                unpublished_analyses.discard(case['id'])
                            except Exception as error:
                                unavailable_state.add(case['id'])
                                interruption.add_note('Prerequisite state recovery failed: '
                                                      f'{type(error).__name__}: {error}')
                        raise
                    if (recheck_execution is not None and info['adopted_solver'] != 'sparse'
                            and case['id'] in prerequisite_ids and len(analyzed) > 1
                            and primary_record.get('row') is not None):
                        try:
                            adapter.analyze(case, work, primary_record['run'])
                        except Exception as exc:
                            primary_record.update(row=None, error='solver recheck state restore failed: '
                                                  f'{type(exc).__name__}: {exc}')
                    outcome['payload'].update(info)
                    recheck_infos[case['id']] = info
                    run_entry['adopted_solver'] = info['adopted_solver']
                    if recheck_execution is not None:
                        run_entry['solver_recheck_run'] = recheck_execution
                    publish(context, outcome, run_entry)
    except BaseException as interruption:
        if isinstance(interruption, Exception):
            raise
        cutoff = getattr(interruption, 'expired_at_monotonic', time.monotonic())
        explicit_dependencies = callable(getattr(adapter, 'analysis_dependencies', None))
        for context in prepared:
            case, _, _, options = context
            if not explicit_dependencies and unpublished_analyses:
                break  # Unknown adapter state cannot be safely replayed.
            if case['id'] in unavailable_state:
                continue
            try:
                if any(key in unavailable_state or key not in all_records
                       or all_records[key].get('error') or all_records[key].get('row') is None
                       for key in dependencies[case['id']]):
                    continue
                if case['id'] not in all_records:
                    execution = receipts.successful(options, before=cutoff)
                    if execution is None:
                        if not explicit_dependencies:
                            break  # Undeclared stateful adapters retain their prefix order.
                        continue
                    primary(context, execution)
                info = recheck_infos.get(case['id'], {})
                if info.get('solver_recheck', {}).get('status') == 'pending':
                    retry = sparse_recheck_arguments(options)
                    second = receipts.successful(retry, before=cutoff)
                    if second is not None:
                        checks = selected_checks if case['id'] in selected_ids else adapter.checks
                        record = analysis_record(case, retry['out'], second, [])
                        second_outcome = case_outcome(checks, case, record)
                        execution, outcome = primary_outcomes[case['id']]
                        outcome, info, _ = completed_solver_recheck(
                            options, execution, outcome, retry, second, second_outcome)
                        outcome['payload'].update(info)
                        recheck_infos[case['id']] = info
                        if (info['adopted_solver'] != 'sparse' and case['id'] in prerequisite_ids
                                and outcome['payload'].get('row') is not None):
                            adapter.analyze(case, options['out'], outcome['payload']['run'])
                        run_entry = run_entries[case['id']]
                        run_entry.update(adopted_solver=info['adopted_solver'], solver_recheck_run=second)
                        publish(context, outcome, run_entry)
            except Exception as error:
                unavailable_state.add(case['id'])
                interruption.add_note(f'Result recovery {case["id"]}: {type(error).__name__}: {error}')
        raise
    complete = (len(result['case_results']) == len(expected_groups(plan)) and
                all(row['status'] in {'passed', 'failed'} for row in result['case_results'].values()))
    selected_groups = {case['score_group'] for case in selected}
    selected_complete = all(result['case_results'][group]['status'] in {'passed', 'failed'}
                            for group in selected_groups)
    error_kinds = {execution.get('error_kind') for execution in executions}
    original_complete = complete and not scope['excluded_case_ids'] and profile == 'full'
    result['coverage']['executed_analysis_count'] = len(executions)
    result.update(status='completed' if selected_complete else 'measurement_failed',
                  passed_case_count=report['passed_group_count'], measurements_complete=selected_complete,
                  evaluation_fully_measured=complete,
                  evaluation_passed=report['passed_group_count'] == len(expected_groups(plan)) if complete else None,
                  original_spec_fully_measured=original_complete,
                  original_spec_passed=report['passed_group_count'] == len(expected_groups(plan)) if original_complete else None,
                  all_requested_passed=all(report['group_results'][group]['passed'] for group in selected_groups))
    if 'environment_error' in error_kinds:
        result.update(status='tool_error', error_kind='environment_error')
    return result
