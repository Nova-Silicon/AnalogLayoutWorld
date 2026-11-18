# Task origins and fixed-circuit adaptations

The paper-v1 release contains 40 fixed-netlist layout tasks: 31 from Analog
Design Bench (ADB), three selected LOADBench design points, two extracted
open-source IP subcircuits, and four team-provided designs ported to SKY130.
The complete per-task source links, revisions, licenses and circuit hashes are
in [sources.json](../configs/paper-v1/sources.json).

The adaptations below define the paper's fixed DUTs and distinguish these
layout tasks from their upstream design references.

## What the source fields mean

- `imported_circuit_sha256` identifies the collected solution, generated
  design-point SPICE snapshot, or extracted subcircuit, as applicable.
- `fixed_circuit_sha256` identifies the actual released `circuit.spice`.
  The public DUT and the independently deployed trusted DUT are byte-identical.
- `released_circuit_matches_imported_bytes` records a byte comparison, not an
  electrical-equivalence proof.
- `netlist_adaptation` describes the released circuit's relationship to that
  reference. Model, terminal and body changes are not assumed electrically
  neutral.

Source licenses remain applicable to their respective materials. Source
attribution does not transfer a third party's content to this project's code
license. Licensing of the four team-provided SKY130 tasks is documented in
[the license scope](../LICENSING.md).

## Analog Design Bench

ADB references are pinned to revision
`972f7cd7c95381134387b250edf18f3bd23bdd25` of
[Arcadia-1/analog-design-bench](https://github.com/Arcadia-1/analog-design-bench/tree/972f7cd7c95381134387b250edf18f3bd23bdd25).
The source records distinguish content under CC-BY-NC-4.0 from code under
Apache-2.0. Per-task links identify the original solution netlist.

The released netlists were compared against those pinned solution snapshots:

| Relationship | Task count |
|---|---:|
| Byte-identical solution netlist | 7 |
| Ideal resistors and/or capacitors replaced by explicit PDK devices | 22 |
| Already-physical resistor families remapped to generic poly | 2 |

The seven byte-identical circuits are LDO-OTA5, low-power oscillator, NMOS-pass
LDO, OTA-5T, regulated charge pump, transistor divide-by-two, and unregulated
charge pump. Their exact task IDs and hashes are recorded in `sources.json`.

For all 31 ADB tasks, the MOS model, terminal and parameter statements were
retained from the pinned reference, comparing SPICE statements without case
or whitespace differences. This does not imply that replacing passive models
preserves the whole circuit's electrical behavior. The released passive model
names, sizes and terminal order belong to the fixed task input; there is no
claim that the adapted netlist is an untouched upstream golden reference.

### Already-physical resistor adaptations

**ADB bandgap, task 3.** Its four upstream resistors already used physical
`res_high_po` or `res_xhigh_po` models. They were replaced by two-terminal
`sky130_fd_pr__res_generic_po` instances, retaining approximately the original
nominal reference resistances. MOS, BJT and MIM statements were retained.
The device family, substrate-terminal representation and voltage/temperature
behavior changed. This is a derived reference, not a correction of model-name
spelling. The final resistor width is 0.33 um; lengths are 41.86, 173.89,
3116.14 and 119843.98 um. The last is about 119.844 mm in electrical length,
with a substantial area and parasitic burden.

**Beta multiplier, task 4.** Its two upstream resistors also were already
physical high/xhigh-poly devices. The final generic-poly core resistor is
W=0.33 um, L=84.13 um; the startup resistor is W=0.33 um, L=5684.65 um.
The nominal core value changed from approximately 14.1849 kOhm to 14.7995 kOhm
(about +4.3%), and the startup value from approximately 15.9 MOhm to 1 MOhm.
The MOS devices were retained. These are actual electrical adaptations, not
an asserted equivalent layout representation. Nominal resistance values are
model-dependent; the fixed geometry and selected model define the task.

### PPSF buffer and FCT amplifier

**PPSF buffer, task 2.** Eight ideal 1 MOhm resistors became generic-poly
devices with W=0.33 um, L=5684.65 um. Eight ideal 5 pF capacitors became
49.85 um square `sky130_fd_pr__cap_mim_m3_1` devices. The MOS statements and
top-level ports were retained. Each resistor has about 5.685 mm electrical
length; the substitution was not optimized for layout area. This task uses
the Magic/Netgen LVS backend.

**FCT residue amplifier, task 10.** Fourteen ideal capacitors became explicit
`sky130_fd_pr__cap_mim_m3_1` instances with dimensions selected on a 0.005 um
grid. MOS statements, clock subcircuits and signal connections were retained.
This task also uses Magic/Netgen LVS. Ideal components in an external
measurement fixture are distinct from components inside the fixed DUT.

The other 20 ideal-passive adaptations use the explicit model families and
replacement counts listed per task in `sources.json`. A source target and a
physical model's nominal value are not identical assertions across process,
voltage, temperature and extracted parasitics.

## LOADBench design points

These three tasks use selected design points from
[LOADBench, DOI 10.5281/zenodo.21759759](https://zenodo.org/records/21759759),
under the recorded CC-BY-4.0 attribution. The source table hashes and the
one-based data-row positions, excluding the header, are preserved in
`sources.json`; MOS W/L, multiplicity and finger count were retained.

| Paper task | Source point | Data row | Released adaptation |
|---|---|---:|---|
| 34 | SimpleOpAmp53 | 952 | Four NMOS body terminals reconnected to `sourceNmos`; top renamed with `BulkTied` |
| 35 | SymmetricalOpAmp3 | 466 | Active SPICE statements unchanged; comments/formatting differ |
| 36 | SimpleTwoStageOpAmp_SimpleOpAmp47_9 | 46 | Five NMOS body terminals reconnected to `sourceNmos`; top renamed with `BulkTied`; compensation capacitor physicalized |

Tasks 34 and 36 are derived circuits: reconnecting a body changes the electrical
circuit and is not a layout-equivalent transformation. D/G/S, device models
and MOS sizing tokens were retained. Task 36 replaces an ideal 2.8 pF
compensation capacitor with a MIM instance of W=L=37.27 um, on the PCell's grid.

Task 35 was not bulk-adapted. Its file is not byte-identical to the selected
SPICE snapshot, but its non-comment SPICE statements are unchanged. It must
not be described as either an untouched byte copy or a bulk-reconnected task.

## Extracted IP subcircuits

Tasks 32 and 33 extract `rc_osc` and `schmitt_trigger` from the schematic netlist
of [ajcci/sky130_ajc_ip__por](https://github.com/ajcci/sky130_ajc_ip__por/tree/db8745ef4d7d85a1852fc60c251ba34c6cebe497),
revision `db8745ef4d7d85a1852fc60c251ba34c6cebe497`, under Apache-2.0.
Their active device statements, including dummy devices, were retained.
The collected standalone subcircuit files and released DUT files are
byte-identical; the upstream full-project schematic file is a different file.
The benchmark defines standalone measurement fixtures and limits for these
blocks. The upstream project did not supply those block-specific benchmark
requirements. Each released task explicitly selects its runtime model library.

## Team-provided SKY130 tasks

Tasks 37–40 are fixed SKY130 versions of team-provided bandgap, comparator,
folded-cascode OTA and two-stage OTA designs. The process adaptations include
device-model and, where applicable, passive-geometry and operating-condition changes.
The folded-cascode task also incorporates the recorded input-feedback polarity
correction. These are separate SKY130 benchmark references; results or targets
from their source process are not proof that a SKY130 implementation passes.

The selected public testbenches and trusted verification cases define the electrical scope
of each released task; a passing task score does not establish untested source
requirements.
