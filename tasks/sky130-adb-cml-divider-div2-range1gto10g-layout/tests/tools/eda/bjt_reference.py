"""LVS-only parallel-unit view for the qualified SKY130 0.68 um PNP.

The installed reader does not expand a BJT instance's SPICE m parameter.
Represent that array as individual identical units, preserving model and pins.
The simulation netlist is not changed. mult is a mismatch parameter, not an
additional nominal unit count, in both installed model-library variants.
"""
import math
import re

MODEL = 'sky130_fd_pr__pnp_05v5_w0p68l0p68'


def bjt_reference_view(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines(keepends=True)
    scope, scopes, existing = [], [], set()
    for number, line in enumerate(lines, 1):
        start = re.match(r'\s*\.subckt\s+(\S+)', line, re.I)
        if start:
            scope.append(start[1].casefold())
        end = re.match(r'\s*\.ends\b(?:[ \t]+([^$;*\s]+))?', line, re.I)
        if end:
            if not scope or (end[1] and end[1].casefold() != scope[-1]):
                raise ValueError(f'Unmatched .ends at line {number}')
            scope.pop()
        scopes.append(tuple(scope))
        instance = re.match(r'\s*([A-Za-z]\S*)\s+', line)
        if instance:
            existing.add((tuple(scope), instance[1].casefold()))
    if scope:
        raise ValueError('Unclosed .subckt in BJT reference')
    mappings = []
    for index, line in enumerate(lines):
        if MODEL not in line.casefold() or line.lstrip().startswith('*'):
            continue
        if index + 1 < len(lines) and lines[index + 1].lstrip().startswith('+'):
            raise ValueError('BJT continuation parameters require explicit normalization')
        match = re.fullmatch(r'([ \t]*)(XQ\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+('
                             + MODEL + r')(?:[ \t]+([^\n]*))?(\n?)', line, re.I)
        if not match:
            raise ValueError('PNP reference requires a normalized XQ name and three pins')
        indent, name, collector, base, emitter, model, params, newline = match.groups()
        params = params or ''
        entries = re.findall(r'(\w+)\s*=\s*([^\s]+)', params)
        pairs = {key.casefold(): value for key, value in entries}
        if (len(pairs) != len(entries) or set(pairs) - {'m', 'mult'}
                or re.sub(r'\w+\s*=\s*[^\s]+', '', params).strip()):
            raise ValueError('PNP reference accepts only literal m/mult; no dropped parameters')
        try:
            numbers = {key: float(value) for key, value in pairs.items()}
        except ValueError as error:
            raise ValueError('PNP m/mult must be literal numbers') from error
        if not all(math.isfinite(value) and value > 0 for value in numbers.values()):
            raise ValueError('PNP m/mult must be positive and finite')
        count = numbers.get('m', 1.0)
        if not count.is_integer():
            raise ValueError('Fractional PNP m has no qualified unit-array representation')
        if count == 1:
            continue
        names, statements = [], []
        for unit in range(int(count)):
            generated = f'{name}__unit{unit+1}'
            key = (scopes[index], generated.casefold())
            if key in existing:
                raise ValueError(f'PNP reference name collision: {generated}')
            existing.add(key)
            names.append(generated)
            statements.append(f'{indent}{generated} {collector} {base} {emitter} {model}')
        lines[index] = '\n'.join(statements) + newline
        mappings.append({'source_instance': name, 'subcircuit_path': list(scopes[index]),
                         'parallel_units': int(count), 'physical_instances': names,
                         'model': model, 'nodes_preserved': [collector, base, emitter],
                         'statistical_mult': numbers.get('mult', 1.0)})
    return ''.join(lines), mappings
