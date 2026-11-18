"""Programmable current source measurement suite."""
from pathlib import Path
from decimal import Decimal, localcontext
import math
import re

from .common import load_source


def predicates(items):
    return [{'name': name, 'passed': bool(ok), 'message': message}
            for name, ok, message in items]


def measured(log: Path, required):
    """Require finite values; repeated prints must agree at printed precision.

    ngspice's meas and print commands emit different decimal precision. Their
    rounding intervals must intersect, including across more than two prints.
    Keep the last value exactly as the frozen source parser does.
    """
    wanted = set(required)
    values = {}
    intervals = {}
    for line in log.read_text(errors='replace').splitlines():
        match = re.match(r'^\s*([^\s=]+)\s*=\s*(\S+)', line)
        if not match or match[1].lower() not in wanted:
            continue
        name = match[1].lower()
        value = float(match[2])
        if not math.isfinite(value):
            raise ValueError(f'Nonfinite source measurement: {name}')
        decimal = Decimal(match[2])
        with localcontext() as context:
            context.prec = max(28, len(decimal.as_tuple().digits) + 2)
            half_unit = Decimal(5).scaleb(decimal.as_tuple().exponent - 1)
            low, high = decimal - half_unit, decimal + half_unit
        if name in intervals:
            prior_low, prior_high = intervals[name]
            low, high = max(low, prior_low), min(high, prior_high)
            # Adjacent values at the same precision only touch at a rounding
            # tie, which cannot justify two different prints at that precision.
            if low >= high:
                raise ValueError(f'Conflicting source measurement: {name}')
        intervals[name] = low, high
        values[name] = value
    if wanted != values.keys():
        raise ValueError(f'Missing source measurements: {sorted(wanted-values.keys())}')
    return values


class ProgrammableMirror:
    slug = 'programmable-icc-iptat-current-mirror-pvt'

    def __init__(self, source_path: Path | None = None, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference

    def plan(self):
        return [{'id': corner+'__'+analysis, 'score_group': corner,
                 'corner': corner, 'analysis': analysis,
                 'profile': 'tt' if corner == self.source.NOMINAL else 'pvt'}
                for corner in self.source.CORNERS for analysis in ('codes_weights', 'compliance')]

    def deck(self, case, design, model):
        text = (self.source.HERE / 'benches' / f'tb_{case["analysis"]}.spi').read_text()
        function = (self.source.codes_weights_substitutions if case['analysis'] == 'codes_weights'
                    else self.source.compliance_substitutions)
        for old, new in function(case['corner']).items():
            if old not in text:
                raise ValueError(f'Frozen source fixture no longer contains {old!r}')
            text = text.replace(old, str(new))
        text = text.replace(self.source.MODEL, str(model)).replace(self.source.DESIGN, str(design))
        return '* Fixed source programmable-current analysis\n' + text, False

    def analyze(self, case, work, run):
        fields = self.source.CW_FIELDS if case['analysis'] == 'codes_weights' else self.source.COMP_FIELDS
        names = [field+'_'+code for code in self.source.CODES for field in fields]
        return {'corner': case['corner'], 'analysis': case['analysis'],
                **measured(work/'ngspice.log', names)}

    def checks(self, case, row):
        if row['corner'] != case['corner'] or row['analysis'] != case['analysis']:
            raise ValueError('Measurement belongs to a different source case')
        if case['analysis'] == 'codes_weights':
            if not self.source.cw_complete(row):
                raise ValueError('Incomplete codes/weights matrix')
            items = self.source.cw_checks(self.source.cw_points([row]))
        else:
            if not self.source.comp_complete(row):
                raise ValueError('Incomplete compliance matrix')
            items = self.source.comp_checks(self.source.comp_points([row]))
        return predicates(items)

    def original_suite_checks(self, rows, run_summary):
        cw = [r for r in rows if r['analysis'] == 'codes_weights']
        comp = [r for r in rows if r['analysis'] == 'compliance']
        if (len(cw) != len(self.source.CORNERS) or len(comp) != len(self.source.CORNERS)
                or {r['corner'] for r in cw} != self.source.CORNERS.keys()
                or {r['corner'] for r in comp} != self.source.CORNERS.keys()):
            return predicates([('source_coverage', False, 'Incomplete original corner matrix')])
        return predicates(self.source.cw_checks(self.source.cw_points(cw)) +
                          self.source.comp_checks(self.source.comp_points(comp)))
