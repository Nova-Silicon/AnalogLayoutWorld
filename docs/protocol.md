# Task and scoring protocol

**English** | [简体中文](protocol.zh-CN.md) · [Documentation](README.md)

The release contains 40 fixed-netlist tasks. Stable task IDs and display numbers
1–40 are listed in `configs/paper-v1/tasks.json`. Each task defines its circuit,
public fixtures, electrical evaluation cases and submission requirements.

## Execution

Each agent attempt has 10,800 seconds for generation, debugging, and self-checks.
Official verification runs afterwards: its outer limit is 3,600 seconds and its
internal budget is 3,300 seconds, leaving time to finalize partial evidence and
collect reports. The actual CPU allocation is passed to verification; parallel
simulation work remains bounded by the available allocation.

Each concurrent trial defaults to 6 CPU and 32 GiB. Formal evaluation uses three
independent attempts per task. The Quick Start runs one attempt.

Two fixed SKY130 model sets are installed. Nine tasks select the original
ngspice/binned library; 31 select combined/continuous. Per-task runtime profiles
preserve these choices.

## Inputs and trust

Agents receive only the task's public environment and instructions. The formal
submission is `submission/layout.gds` plus Python source under `submission/src/`;
README is optional. The GDS is evaluated; submitted code and submitted reports
are never executed as trusted evidence.

After the agent ends, Harbor transfers only the declared submission to a fresh
verifier container. The verifier uses its own task inputs and trusted tests,
checks input/tool manifests, and runs with networking disabled. Agent workspace
edits do not change the trusted reference circuit or scoring configuration.

## Scoring

Six nonnegative contributions are added:

| Contribution | Weight |
|---|---:|
| GDS presence | 0.10 |
| LVS | 0.10 |
| DRC | 0.10 |
| Effective area | 0.20 |
| Engineering quality | 0.10 |
| Post-layout simulation | 0.40 |

LVS failure withholds the subsequent engineering bonuses. A failed DRC does not
automatically withhold every later contribution. Aspect ratio, minimum effective
area ratio, and the fixed morphology screen gate the applicable bonuses according
to the scorer. Their exact per-task values are in the versioned parameter file.
The area exponent is 2, with completion capped at 1.

Effective area comes from extracted, reference-corresponding devices. It is not
a sum of PCell bounding boxes and is not a W×L-only estimate. MOS contributions
include channel and source/drain diffusion areas; native resistor/capacitor area
and BJT recognition regions are used. Different devices may overlap, so the raw
ratio can exceed 1.

Engineering quality uses programmatic matching, critical-routing and power
measurements. Category weights are 0.40/0.45/0.15, with independent saturation
targets 0.80/0.80/0.90. No LLM judge is used. Inapplicable categories leave the
denominator; missing applicable evidence keeps its weight with value zero.
Required missing coupling evidence withholds the corresponding quality credit.

Post-layout credit uses the fraction of fixed required evaluation items that
completed and passed, after successful extraction. Unfinished items stay in the
denominator. Verified completed passes survive an internal time limit; unknown
results never become presumed passes. A lower-bound score and a complete measured
score remain distinguishable in the report.

Passing a selected public testbench scope does not claim that every condition in
the upstream source specification was simulated. The electrical scope and omitted
conditions remain explicit in evaluation output.

The fixed parameter source is `src/analoglayoutworld/data/paper-v1.json`.

## Reports

Read `evaluation/metrics.json` together with its stage reports. `score_valid`
indicates usable scoring evidence; `evaluation_error` marks a verifier or
evidence error. `pipeline_completed` records pipeline completion,
while `design_passed` records whether the design passed. `score_is_lower_bound`
indicates verified partial credit with requirements still pending; it does not
mean that the design passed.

Harbor output paths are documented under [results](running.md#results).
For standalone `alw verify` commands, reports and exit codes, see
[existing-GDS evaluation](running.md#existing-gds).

