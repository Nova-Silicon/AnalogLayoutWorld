"""Run trusted task measurement cases on a supplied DUT netlist.

The ngspice execution primitive is eda.simulation. Task declarations specify
stimuli, analyses, measurements and bounds; this module never chooses SPECs.
"""
from __future__ import annotations

import argparse
from functools import partial
import importlib.util
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import time

try:
    from .runtime import cleanup_on_termination, load_runtime, shared_output
    from .pex import (LIMITATION, declared_subckt_pins, inspect_netlist, load_task, logical_lines,
                      port_keys, reference_floating_ports, required_extracted_ports)
    from .simulation import (run_deck, parse_measurements, ordered_deck_runs,
                             recheck_failed_analysis, solver_recheck_summary,
                             primary_analysis_checkpoint, completed_solver_recheck,
                             sparse_recheck_arguments)
    from .simulation_progress import NativeExecutionReceipts, atomic_json
    from .simulation_resources import positive_integer, simulation_resources, configure_deck_threads
except ImportError:
    from runtime import cleanup_on_termination, load_runtime, shared_output
    from pex import (LIMITATION, declared_subckt_pins, inspect_netlist, load_task, logical_lines,
                     port_keys, reference_floating_ports, required_extracted_ports)
    from simulation import (run_deck, parse_measurements, ordered_deck_runs,
                            recheck_failed_analysis, solver_recheck_summary,
                            primary_analysis_checkpoint, completed_solver_recheck,
                            sparse_recheck_arguments)
    from simulation_progress import NativeExecutionReceipts, atomic_json
    from simulation_resources import positive_integer, simulation_resources, configure_deck_threads

# Capacitor-only extracted nodes can make the DC matrix singular. The qualified
# post-layout default adds a weak DC path; it does not make every convergence
# fallback invalid, nor guarantee that the resulting measurements pass SPEC.
# Keep the task's initialization text and let its own settings take precedence.
# Testbench decks and reference (pre-layout) initialization are not rewritten.
FLOATING_NODE_SHUNT = 'option rshunt=1e14\n'
FLOATING_NODE_SHUNT_POLICY = {
    'id': 'extracted-floating-node-rshunt-v1',
    'option': FLOATING_NODE_SHUNT.strip(),
    'scope': 'post-layout (extracted) .spiceinit; task settings take precedence',
    'reason': 'provide a weak DC path for capacitor-only extracted nodes',
}
_SPICE_NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?[a-z]*', re.I)


def _initialization_shunt_value(initialization: str) -> tuple[bool, str | None]:
    """Recognize simple initialization only, without interpreting Nutmeg code.

    Return (statically understood, last rshunt value). Quoted values/comments
    are tokenized before matching names, so an unrelated string cannot pretend
    to configure rshunt. Scripts/expansions are left to ngspice, with no claim
    about their final value. Dot-prefixed .options is a deck directive, not an
    initialization command.
    """
    value = None
    for line in initialization.splitlines():
        if not line.strip() or line.lstrip().startswith('*'):
            continue
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars='=')
            lexer.whitespace_split = True
            lexer.commenters = ';'
            tokens = list(lexer)
        except ValueError:
            return False, None
        if not tokens:
            continue
        command = tokens[0].lower()
        if command not in {'set', 'option', 'options'} or any(
                char in line.split(';', 1)[0] for char in ('$','`','\\')):
            return False, None
        index = 1
        while index < len(tokens):
            name = tokens[index].lower()
            if not re.fullmatch(r'[a-z_][a-z_0-9]*', name):
                return False, None
            index += 1
            assigned = index < len(tokens) and tokens[index] == '='
            if assigned:
                index += 1
                if index == len(tokens):
                    return False, None
                assigned_value = tokens[index]
                index += 1
            if name == 'rshunt':
                if command == 'set' or not assigned or not _SPICE_NUMBER.fullmatch(assigned_value):
                    return False, None
                value = assigned_value
    return True, value


def _floating_node_shunt_configuration(initialization: str, *, reference: bool = False) -> tuple[str, dict]:
    """Keep the executed initialization and its policy record in agreement."""
    if reference:
        return initialization, {}
    known, task_value = _initialization_shunt_value(initialization)
    preserve = known and task_value is not None
    configured = initialization if preserve else FLOATING_NODE_SHUNT + initialization
    value = task_value if preserve else '1e14' if known else None
    record = {**FLOATING_NODE_SHUNT_POLICY,
              'option': f'option rshunt={value}' if value is not None else None,
              'default_option': FLOATING_NODE_SHUNT.strip(),
              'default_inserted': not preserve,
              'configuration_source': 'task' if preserve else 'default' if known else 'task_script',
              'initialization_value': value,
              'initialization_value_known': known}
    return configured, {'floating_node_shunt': record}


def with_floating_node_shunt(initialization: str, *, reference: bool = False) -> str:
    """Supply a post-layout default without overriding task initialization.

    Simple explicit rshunt assignments are retained without duplication. For
    scripts, put the default first and let ngspice run the original text after
    it. This helper does not attempt to evaluate the script's control flow.
    """
    return _floating_node_shunt_configuration(initialization, reference=reference)[0]


def measurement_settings(task: Path) -> dict:
    path = task / 'testbench/measurement.json'
    if not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if isinstance(value, dict) and 'solver_policy' in value:
        if value['solver_policy'] not in ('auto', 'sparse', 'klu'):
            raise ValueError('solver_policy must be auto, sparse or klu')
    if isinstance(value, dict) and 'solver_policy_reason' in value:
        if ('solver_policy' not in value or not isinstance(value['solver_policy_reason'], str)
                or not value['solver_policy_reason'].strip()):
            raise ValueError('solver_policy_reason requires a solver_policy and nonempty text')
    if isinstance(value, dict) and 'evaluation_case_ids' in value:
        selected = value['evaluation_case_ids']
        if (not isinstance(selected, list) or not selected
                or any(not isinstance(key, str) or not key for key in selected)):
            raise ValueError('evaluation_case_ids must be a nonempty list of analysis IDs')
    if isinstance(value, dict) and 'qualification_case_ids' in value:
        extra = value['qualification_case_ids']
        if 'evaluation_case_ids' not in value:
            raise ValueError('qualification_case_ids requires evaluation_case_ids')
        if (not isinstance(extra, list) or not extra
                or any(not isinstance(key, str) or not key for key in extra)):
            raise ValueError('qualification_case_ids must be a nonempty list of analysis IDs')
        if set(extra) & set(value['evaluation_case_ids']):
            raise ValueError('qualification_case_ids must not repeat scored evaluation_case_ids')
    return value if isinstance(value, dict) else {}


def selected_case_ids(settings: dict, reference: bool = False) -> list[str] | None:
    """Analyses to run: the scored selection, plus qualification-only analyses
    (for example full Monte Carlo seed sets) when the input is the reference
    netlist. Post-layout scoring never includes qualification analyses."""
    selected = settings.get('evaluation_case_ids')
    extra = settings.get('qualification_case_ids')
    if reference and extra:
        return list(selected) + list(extra)
    return selected


def load_processor(task: Path):
    """Load only the processor named by the trusted measurement manifest."""
    name = measurement_settings(task).get('processor')
    if name is None:
        return None
    root = (task / 'testbench').resolve()
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or path.suffix != '.py':
        raise ValueError('Processor must be a Python module under trusted task/testbench')
    module_spec = importlib.util.spec_from_file_location('alb_task_measurement_processor', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if not callable(getattr(module, 'process_case', None)):
        raise ValueError('Processor must export process_case(case, work, values)')
    return module.process_case


def load_cases(task: Path) -> list[dict]:
    path = next((p for p in (task / 'testbench/measurement.json', task / 'testbench/cases.json') if p.is_file()), None)
    if path is None:
        raise ValueError('Task has no testbench/measurement.json or cases.json; measurement adapter is not configured')
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        if data.get('schema_version') != 1:
            raise ValueError('Unsupported measurement schema')
        data = data.get('cases')
    if not isinstance(data, list) or not data:
        raise ValueError('Measurement cases must be a nonempty list')
    ids = set()
    for case in data:
        case_id = case.get('id')
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError('Duplicate or empty measurement case id')
        ids.add(case_id)
        if 'score_group' in case and (not isinstance(case['score_group'], str) or not case['score_group']):
            raise ValueError(f'{case_id}: score_group must be a nonempty string')
        if not isinstance(case.get('deck'), str) or '__DUT_NETLIST__' not in case['deck']:
            raise ValueError(f'{case_id}: deck must include the DUT placeholder')
        limits = case.get('required_measurements')
        if not isinstance(limits, dict) or not limits:
            raise ValueError(f'{case_id}: required_measurements missing')
        for name, bounds in limits.items():
            if not isinstance(bounds, dict) or not ({'min', 'max'} & set(bounds)) or set(bounds) - {'min', 'max', 'unit'}:
                raise ValueError(f'{case_id}/{name}: unsupported measurement bounds')
            for key in ('min', 'max'):
                if key in bounds and (not isinstance(bounds[key], (int, float)) or not math.isfinite(bounds[key])):
                    raise ValueError(f'{case_id}/{name}: nonfinite bound')
            if 'min' in bounds and 'max' in bounds and bounds['min'] > bounds['max']:
                raise ValueError(f'{case_id}/{name}: reversed bounds')
        for name, recipe in case.get('derived', {}).items():
            if not isinstance(recipe, dict) or set(recipe) - {'source', 'scale', 'offset'} or not isinstance(recipe.get('source'), str):
                raise ValueError(f'{case_id}/{name}: unsupported derived measurement')
            if not all(isinstance(recipe.get(key, default), (int, float)) and math.isfinite(recipe.get(key, default)) for key, default in (('scale', 1), ('offset', 0))):
                raise ValueError(f'{case_id}/{name}: invalid affine transformation')
    return data


def select_cases(cases: list[dict], profile: str) -> list[dict]:
    return [case for case in cases if profile == 'full' or case.get('profile') == 'tt' or
            (str(case.get('corner', '')).lower() == 'tt' and case.get('temperature_C', 27) == 27)]


def metric_key(case: dict, name: str) -> str:
    return f"{case['id']}/{name}" if 'score_group' in case else name


def aggregate_cases(cases: list[dict], raw: dict, expected: dict) -> dict:
    """A PVT group passes only if every required analysis in that group passes."""
    grouped = {}
    for case in cases:
        if case['id'] not in raw:
            continue
        group = case.get('score_group', case['id'])
        entry = grouped.setdefault(group, {'measurements': {}, 'source_case_ids': [], 'error_kinds': []})
        item = raw[case['id']]
        entry['source_case_ids'].append(case['id'])
        entry['measurements'].update({metric_key(case, name): row for name, row in item['measurements'].items()})
        if item.get('error_kind'):
            entry['error_kinds'].append(item['error_kind'])
    for group, entry in grouped.items():
        rows = entry['measurements']
        complete = set(expected[group]) <= set(rows) and all(rows[name]['value'] is not None for name in expected[group])
        passed = complete and all(rows[name]['passed'] for name in expected[group]) and not entry['error_kinds']
        entry.update(passed=bool(passed), status='error' if entry['error_kinds'] else 'passed' if passed else 'failed' if complete else 'incomplete')
    return grouped


def expected_cases(task: Path, profile: str = 'full', *, reference: bool = False) -> dict[str, dict]:
    """Return trusted case IDs and mandatory limits, independent of run results.

    The default (post-layout scoring) excludes qualification-only analyses."""
    if profile not in {"tt", "full"}:
        raise ValueError("Unsupported profile")
    settings = measurement_settings(task)
    if 'suite' in settings:
        from . import suite_runner
        adapter = suite_runner.load_adapter(task, settings)
        plan = suite_runner.evaluation_plan(adapter.plan(), selected_case_ids(settings, reference))
        suite_runner.selected_reducer(adapter, plan)
        if profile == 'tt':
            plan = [case for case in plan if case.get('profile') == 'tt']
        return suite_runner.expected_groups(plan)
    cases = load_cases(task)
    from .suite_runner import evaluation_plan
    cases = evaluation_plan(cases, selected_case_ids(settings, reference))
    result = {}
    for case in select_cases(cases, profile):
        group = case.get('score_group', case['id'])
        required = result.setdefault(group, {})
        for name, bounds in case['required_measurements'].items():
            key = metric_key(case, name)
            if key in required:
                raise ValueError(f'Duplicate grouped metric: {group}/{key}')
            required[key] = bounds
    return result


def make_adapter(task: Path, netlist: Path, out: Path) -> tuple[Path, dict]:
    contract = load_task(task)
    subckts = declared_subckt_pins(netlist)
    preferred = next((name for name in (contract['top'], contract['top'] + '_pex') if name.lower() in subckts), None)
    floating = reference_floating_ports(task / 'circuit.spice', contract['top'], contract['ports'])['ports']
    # A floating reference port may legitimately be absent from the extracted
    # top. It is then left unconnected inside the adapter; all others remain
    # required. Without an identified top, the historical full contract applies.
    required, absent = required_extracted_ports(
        contract['ports'], floating, subckts[preferred.lower()] if preferred else None)
    info = inspect_netlist(netlist, required, preferred)
    if floating:
        info['floating_reference_ports'] = {
            'ports': floating, 'absent_from_extracted_top': absent,
            'connected_in_adapter': [port for port in floating if port not in absent],
            'handling': ('Absent floating reference ports remain ports of the adapter subcircuit '
                         'but are not passed to the extracted subcircuit; the testbench node is '
                         'unchanged and no device is attached to it.') if absent else
                        'Present in the extracted top and connected as usual.'}
    if absent and info['top'].lower() == contract['top'].lower():
        raise ValueError('Same-name DUT lacks a floating reference port; an adapter rename is required')
    snapshot = out / 'input.spice'
    shutil.copyfile(netlist, snapshot)
    for path in (snapshot,):
        if any(char in str(path) for char in ('"', '\n', '\r')):
            raise ValueError('Unsupported quoted SPICE path')
    adapter = out / 'dut_adapter.spi'
    text = f'* The DUT is unchanged; only a subcircuit/pin-order adapter is added.\n.include "{snapshot}"\n'
    if absent:
        text += ('* Floating reference port(s) absent from the extracted top, left unconnected: '
                 + ' '.join(absent) + '\n')
    binding = dict(zip(port_keys(contract['ports']), contract['ports']))
    instance_ports = [binding[key] for key in port_keys(info['ports'])]
    if info['top'].lower() != contract['top'].lower():
        text += f'.subckt {contract["top"]} {" ".join(contract["ports"])}\nXDUT {" ".join(instance_ports)} {info["top"]}\n.ends {contract["top"]}\n'
    elif [p.lower() for p in info['ports']] != [p.lower() for p in contract['ports']]:
        raise ValueError('Same-name DUT has reordered ports; supply an explicitly renamed extracted subcircuit')
    adapter.write_text(text)
    return adapter, info


def prepare_case_deck(case: dict, adapter: Path, model: Path, *, reference: bool = False,
                      source_geometry_scale: float | None = None,
                      extracted_geometry_scale: float | None = None) -> tuple[str, list[dict]]:
    """Replace declared dependencies; only explicit unit declarations allow scaling.

    SKY130 Magic ngspice()/scale-off outputs PDK X device dimensions in microns,
    not SI. Most source benches therefore require NO scale change. No dimensions
    or simulation options are guessed from the file's name or tool's mode.
    """
    source = case['deck'].replace('__DUT_NETLIST__', str(adapter)).replace('__MODEL_LIB__', str(model))
    changes = []
    if not reference and source_geometry_scale is not None and extracted_geometry_scale is not None:
        if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in (source_geometry_scale, extracted_geometry_scale)):
            raise ValueError('Invalid geometry scale declaration')
        if not math.isclose(source_geometry_scale, extracted_geometry_scale, rel_tol=1e-12):
            def reset_scale(match):
                if not math.isclose(float(match[2]), source_geometry_scale, rel_tol=1e-12):
                    raise ValueError('Manifest source_geometry_scale differs from bench scale')
                changes.append({'source_scale': match[2], 'extracted_scale': extracted_geometry_scale,
                                'reason': 'Explicit task geometry-unit declaration'})
                return match[1] + format(extracted_geometry_scale, '.12g')
            source = re.sub(r'(?im)(^\s*\.options?\b[^\n]*?\bscale\s*=\s*)([^\s]+)', reset_scale, source)
            if not changes:
                raise ValueError('Unit conversion requires an explicit .option scale in the testbench')
    if re.search(r'__[A-Z_]+__', source):
        raise ValueError('Unresolved testbench placeholder')
    return source, changes


def simulate(task: Path, netlist: Path, out: Path, profile: str, timeout: float,
             *, reference: bool = False, workers: int = 1,
             cpu_budget: int | None = None, solver_recheck: bool = False) -> dict:
    """Run trusted cases. ``solver_recheck`` (post-layout verifier only) reruns
    an analysis that failed with policy-selected KLU once with SPARSE and
    records both attempts; see eda.simulation.recheck_failed_analysis."""
    positive_integer(workers, 'Simulation workers')
    if cpu_budget is not None:
        positive_integer(cpu_budget, 'Simulation CPU budget')
    if profile not in {'tt', 'full'}:
        raise ValueError('Unsupported profile')
    if type(solver_recheck) is not bool:
        raise ValueError('solver_recheck must be a Boolean')
    if solver_recheck and reference:
        raise ValueError('The solver recheck applies to post-layout simulation only')
    settings = measurement_settings(task)
    initialization = settings.get('initialization', 'set num_threads=1\n')
    if not isinstance(initialization, str):
        raise ValueError('Task simulation initialization must be text')
    initialization, shunt_record = _floating_node_shunt_configuration(initialization, reference=reference)
    # A qualified task-specific choice overrides the global verifier default
    # without mutating process environment shared by concurrent simulations.
    solver = settings.get('solver_policy')
    runner = run_deck if solver is None else partial(run_deck, solver_policy=solver)
    solver_configuration = ({'policy': solver, 'reason': settings.get('solver_policy_reason')}
                            if solver is not None else None)
    model = Path(settings.get('model_library', load_runtime()['model_lib']))
    if not model.is_absolute():
        raise ValueError('Trusted task model_library must be an absolute path')
    if 'suite' in settings:
        from . import suite_runner
        suite = suite_runner.load_adapter(task, settings, reference=reference)
        out = shared_output(out)
        dut, info = make_adapter(task, netlist, out)
        result = suite_runner.simulate(suite, dut, model, out,
                                       timeout, profile=profile, run_deck=runner,
                                       initialization=initialization, workers=workers,
                                       cpu_budget=cpu_budget,
                                       evaluation_case_ids=selected_case_ids(settings, reference),
                                       **({'execution_metadata': shunt_record} if shunt_record else {}),
                                       **({'solver_recheck': True} if solver_recheck else {}))
        result.update(netlist=info, initialization=initialization, **shunt_record,
                      input_kind='reference' if reference else 'extracted',
                      limitations=[] if reference else [LIMITATION,
                          'Extracted RC remains fixed while device models and bench PVT vary.'])
        if solver_configuration is not None:
            result['solver_policy_override'] = solver_configuration
        return result
    cases = load_cases(task)
    from .suite_runner import evaluation_plan, coverage
    source_cases = cases
    cases = evaluation_plan(source_cases, selected_case_ids(settings, reference))
    scope = coverage(source_cases, cases)
    out = shared_output(out)
    adapter, info = make_adapter(task, netlist, out)
    processor = load_processor(task)
    expected = expected_cases(task, 'full', reference=reference)
    selected = {case['id'] for case in select_cases(cases, profile)}
    if not selected:
        raise ValueError('No cases selected for this diagnostic profile')
    resources = simulation_resources(workers, len(selected), cpu_budget)
    result = {'status': 'running', 'profile': profile,
              'scope': ('selected_evaluation' if scope['excluded_case_ids'] else 'full')
                       if profile == 'full' else 'diagnostic',
              'coverage': scope,
              'input_netlist': str(netlist), 'netlist': info, 'model_lib': str(model),
              'initialization': initialization, **shunt_record, **resources.record(),
              'input_kind': 'reference' if reference else 'extracted',
              'expected_case_ids': list(expected), 'required_case_count': len(expected),
              'case_results': {}, 'raw_case_results': {}, 'runs': [], 'measurements': [],
              'limitations': [] if reference else [LIMITATION, 'Extracted RC remains fixed while device models and bench PVT vary.']}
    prepared = []
    receipts = NativeExecutionReceipts(runner)

    def requests():
        for index, case in enumerate(cases):
            if case['id'] not in selected:
                continue
            work = out / f'case_{index:04d}'
            work.mkdir()
            source, changes = prepare_case_deck(case, adapter, model, reference=reference,
                source_geometry_scale=settings.get("source_geometry_scale"),
                extracted_geometry_scale=settings.get("extracted_geometry_scale"))
            thread_changes = []
            if resources.threads_per_worker is not None:
                source, thread_changes = configure_deck_threads(source, resources.threads_per_worker)
            deck = work / 'testbench.spi'
            deck.write_text(source)
            options = {'deck': deck, 'out': work, 'timeout': timeout,
                       'initialization': initialization}
            if resources.threads_per_worker is not None:
                options['num_threads'] = resources.threads_per_worker
            context = (case, work, changes, thread_changes, options)
            prepared.append(context)
            yield context, options

    def measure(case, work, changes, execution):
        """Judge one native execution against the case's trusted bounds."""
        required = case['required_measurements']
        derived = case.get('derived', {})
        raw_keys = set(required) - set(derived)
        raw_keys.update(recipe['source'] for recipe in derived.values())
        values, problems = parse_measurements(Path(execution['command']['log_path']).read_text(errors='replace'), sorted(raw_keys))
        for name, recipe in derived.items():
            value = values.get(recipe['source'])
            if value is not None:
                transformed = value * recipe.get('scale', 1) + recipe.get('offset', 0)
                if math.isfinite(transformed):
                    values[name] = transformed
                else:
                    problems[name] = 'non-finite derived value'
            else:
                problems[name] = 'missing or invalid source measurement'
        processor_error = None
        if processor is not None and execution['status'] == 'completed':
            try:
                extra = processor(case, work, dict(values))
                if not isinstance(extra, dict):
                    raise ValueError('Processor output must be a metric/value mapping')
                for name, value in extra.items():
                    if name in values:
                        raise ValueError(f'Processor would overwrite a measured value: {name}')
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError(f'Processor returned invalid scalar: {name}')
                    values[name] = float(value)
                    problems.pop(name, None)
            except Exception as exc:
                processor_error = f'{type(exc).__name__}: {exc}'
                # Do not guess that missing waveforms are an environment fault.
                execution.update(status='tool_error', error_kind='measurement_processor_error')
        measurements = {}
        for name, bounds in required.items():
            value = values.get(name) if execution['status'] == 'completed' else None
            passed = value is not None and ('min' not in bounds or value >= bounds['min']) and ('max' not in bounds or value <= bounds['max'])
            measurements[name] = {'value': value, 'passed': bool(passed), 'limits': bounds,
                                  'status': 'measured' if value is not None else 'missing_or_invalid',
                                  'error': problems.get(name) if execution['status'] == 'completed' else execution.get('error_kind')}
        complete = all(row['value'] is not None for row in measurements.values())
        passed = complete and all(row['passed'] for row in measurements.values())
        entry = {'status': 'error' if execution['status'] != 'completed' else 'passed' if passed else 'failed' if complete else 'incomplete',
                 'passed': bool(passed), 'measurements': measurements, 'command': execution['command'],
                 'error_kind': execution.get('error_kind'), 'processor_error': processor_error, 'geometry_scale_adjustments': changes}
        return {'passed': bool(passed), 'payload': entry, 'detail': {'measurements': measurements},
                'evidence': {'verdict': entry['status'], 'passed': bool(passed),
                             'error': processor_error or entry['error_kind'],
                             'failed_measurements': [name for name, row in measurements.items()
                                                     if not row['passed']]}}

    if solver_configuration is not None:
        result['solver_policy_override'] = solver_configuration
    recheck_infos = {}
    run_entries = {}
    primary_outcomes = {}

    def publish(case, outcome, execution):
        result['raw_case_results'][case['id']] = outcome['payload']
        run_entries[case['id']] = execution
        # Keep final arrays in the original plan order, also after replacing a
        # provisional primary verdict with the adopted solver verdict.
        result['runs'] = [run_entries[c['id']] for c in cases if c['id'] in run_entries]
        result['measurements'] = [
            {'case_id': c['id'], 'metric': name, **row}
            for c in cases if c['id'] in result['raw_case_results']
            for name, row in result['raw_case_results'][c['id']]['measurements'].items()]
        result['case_results'] = aggregate_cases(cases, result['raw_case_results'], expected)
        if solver_recheck:
            summary = solver_recheck_summary(recheck_infos)
            result.update(solver_recheck=summary,
                          solver_disagreement=bool(summary['disagreement_case_ids']))
        atomic_json(out / 'metrics.json', result)

    def primary(context, execution):
        case, work, changes, thread_changes, options = context
        execution['thread_configuration_changes'] = thread_changes
        outcome = measure(case, work, changes, execution)
        primary_outcomes[case['id']] = (execution, outcome)
        run_entry = {'case_id': case['id'], **execution}
        if solver_recheck:
            info = primary_analysis_checkpoint(options, execution, outcome)
            outcome['payload'].update(info)
            recheck_infos[case['id']] = info
            run_entry['adopted_solver'] = info['adopted_solver']
        publish(case, outcome, run_entry)
        return outcome, run_entry

    atomic_json(out / 'metrics.json', result)
    try:
        with ordered_deck_runs(requests(), receipts, resources.workers) as executions:
            for context, execution in executions:
                case, work, changes, thread_changes, options = context
                outcome, run_entry = primary(context, execution)
                if (solver_recheck and recheck_infos[case['id']]['solver_recheck']['status'] == 'pending'):
                    def judge(run_execution, directory):
                        run_execution['thread_configuration_changes'] = thread_changes
                        return measure(case, directory, changes, run_execution)

                    outcome, info, recheck_execution = recheck_failed_analysis(
                        receipts, options, execution, outcome, judge)
                    outcome['payload'].update(info)
                    recheck_infos[case['id']] = info
                    run_entry['adopted_solver'] = info['adopted_solver']
                    if recheck_execution is not None:
                        run_entry['solver_recheck_run'] = recheck_execution
                    publish(case, outcome, run_entry)
    except BaseException as interruption:
        if isinstance(interruption, Exception):
            raise  # Ordinary failures retain their original handling.
        # Native cleanup has finished. Only a successful runner return can be
        # recovered; waveform/log existence alone is never completion evidence.
        # Declared cases and their processors are independent per-case inputs.
        # No new simulation or solver recheck is started while unwinding.
        cutoff = getattr(interruption, 'expired_at_monotonic', time.monotonic())
        for context in prepared:
            case, _, changes, thread_changes, options = context
            try:
                if case['id'] not in run_entries:
                    execution = receipts.successful(options, before=cutoff)
                    if execution is not None:
                        primary(context, execution)
                info = recheck_infos.get(case['id'], {})
                if info.get('solver_recheck', {}).get('status') == 'pending':
                    retry = sparse_recheck_arguments(options)
                    second = receipts.successful(retry, before=cutoff)
                    if second is not None:
                        second['thread_configuration_changes'] = thread_changes
                        second_outcome = measure(case, retry['out'], changes, second)
                        execution, outcome = primary_outcomes[case['id']]
                        outcome, info, _ = completed_solver_recheck(
                            options, execution, outcome, retry, second, second_outcome)
                        outcome['payload'].update(info)
                        recheck_infos[case['id']] = info
                        run_entry = run_entries[case['id']]
                        run_entry.update(adopted_solver=info['adopted_solver'], solver_recheck_run=second)
                        publish(case, outcome, run_entry)
            except Exception as error:
                # A damaged saved output must not mask the original budget or
                # termination exception and invalidate previously saved credit.
                interruption.add_note(f'Result recovery {case["id"]}: {type(error).__name__}: {error}')
        raise
    observed = result['case_results']
    complete = len(observed) == len(expected) and all(row['status'] in {'passed', 'failed'} for row in observed.values())
    all_selected_complete = all(row['status'] in {'passed', 'failed'} for row in observed.values())
    errors = {row['error_kind'] for row in result['raw_case_results'].values() if row['error_kind']}
    status = 'tool_error' if errors else 'completed' if all_selected_complete else 'measurement_failed'
    original_complete = complete and not scope['excluded_case_ids']
    result['coverage']['executed_analysis_count'] = len(result['runs'])
    result.update(status=status, passed_case_count=sum(row['passed'] for row in observed.values()),
                  measurements_complete=all_selected_complete,
                  all_requested_passed=all(row['passed'] for row in observed.values()),
                  evaluation_fully_measured=complete,
                  evaluation_passed=all(row['passed'] for row in observed.values()) if complete else None,
                  original_spec_fully_measured=original_complete,
                  original_spec_passed=all(row['passed'] for row in observed.values()) if original_complete else None)
    if errors:
        result['error_kind'] = next((kind for kind in ('environment_error', 'measurement_processor_error', 'timeout', 'execution_error') if kind in errors), 'execution_error')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--profile', choices=('tt', 'full'), default='full')
    parser.add_argument('--reference', action='store_true', help='Input is the source netlist, retain its geometry scale')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--cpus', type=int, help='CPU budget shared by workers and ngspice threads')
    args = parser.parse_args(argv)
    out = shared_output(args.out)
    out.mkdir(parents=True, exist_ok=False)
    try:
        with cleanup_on_termination():
            result = simulate(args.task.resolve(strict=True), args.netlist.resolve(strict=True), out, args.profile, args.timeout, reference=args.reference, workers=args.workers, cpu_budget=args.cpus)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {'status': 'tool_error', 'error_kind': 'invalid_input', 'profile': args.profile,
                  'error': str(exc), 'original_spec_passed': None}
    (out / 'metrics.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result, allow_nan=False))
    return 2 if result['status'] != 'completed' else 0 if result['all_requested_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
