# Source and license notices

This benchmark combines original software with third-party software and task
content. Original project material uses Apache-2.0, with the scope and exceptions
defined in `LICENSING.md`. File-specific notices take precedence; this document
does not relicense third-party materials.

## Paper figure

The README overview figure (paper Figure 3) includes a cropped waveform by the
KiCad Documentation Contributors from the [KiCad Schematic Editor Reference Manual, version 9.0](https://docs.kicad.org/9.0/en/eeschema/eeschema.html),
licensed under [CC-BY-3.0 or later](https://creativecommons.org/licenses/by/3.0/).

## Task sources

| Source | Included tasks | Recorded license |
|---|---:|---|
| Analog Design Bench | 31 | Software Apache-2.0; benchmark content CC-BY-NC-4.0 |
| LOADBench | 3 | CC-BY-4.0 |
| Public SKY130 circuit repositories | 2 | Apache-2.0 |
| Original benchmark designs | 4 | Apache-2.0 for original task material |

- Analog Design Bench: https://github.com/Arcadia-1/analog-design-bench , pinned
  source revision `972f7cd7c95381134387b250edf18f3bd23bdd25`. Upstream task
  definitions, circuits, and testbench material retain their respective notices.
  See `LICENSES/Analog-Design-Bench-LICENSING.txt`.
- LOADBench: Markus Leibl, Filipe Azevedo, Stefan Uhlich, Andrea Bonetti, Arun
  Venkitaraman, Chia-Yu Hsieh, Phuoc Pham, Lorenzo Servadei, Helmut Graeb, and
  Ricardo Martins. DOI https://doi.org/10.5281/zenodo.21759759 , CC-BY-4.0.
  Local fixed-netlist, bulk-connection and testbench adaptations are documented
  in the source manifest.
- The two internet-derived subcircuits come from
  https://github.com/ajcci/sky130_ajc_ip__por at
  `db8745ef4d7d85a1852fc60c251ba34c6cebe497`. Standalone benchmark constraints
  and testbenches are adaptations; the upstream project did not define these
  task-specific acceptance limits.

The [source manifest](configs/paper-v1/sources.json) records the upstream
source and adaptations for each task.

## EDA environment

The Docker image installs third-party software under its original licenses:
Ubuntu packages, CPython, KLayout, Magic, Netgen, ngspice, Node.js, ripgrep, and
the pinned Python dependencies. Source URLs and checksums are in
`docker/sources.lock.json` and `docker/python-artifacts.lock.json`.

The vendored SKY130 runtime tree retains the gdsfactory SKY130 package's MIT
license, model licenses, open_pdks license, and the distinct licenses of the
selected KLayout DRC and LVS decks. Full notices and fixed source revisions are
under `docker/pdk/sky130/licenses/` and its asset manifest. These materials are a
qualified task subset, not the entire upstream PDK distribution.

Rebuilt native-tool license texts and runtime provenance are installed into the
image. Additional software installed by a user's chosen agent retains its own
license and is not relicensed by this benchmark.

The canonical verifier also includes `src/eda/sky130_dummy_purge_20261103_v2.lvs`,
an adapted Efabless SKY130 LVS deck. It retains the original Apache-2.0 copyright
header and dated modification notes. Its wheel copy is
`eda/sky130_dummy_purge_20261103_v2.lvs`; the wheel carries this notice and the
complete applicable license texts under its distribution metadata.

## Optional harness adapters

The optional adapters under `src/analoglayoutworld_agents/` are project-original
integration code. Harbor is a separately installed Apache-2.0 dependency; the
official DSH runtime is a separately downloaded MIT package. DSH's transitive
dependencies retain their own licenses and installed notices. The DSH build
lock and public-source recipe are supplied under `harnesses/deepseek-harness/`;
the benchmark does not relicense or redistribute its generated runtime bundle.

