# Pinned SKY130 runtime assets

The Python PCells and their fixed-cell GDS resources are unmodified upstream
library assets, not benchmark task solutions. `asset-manifest.json` lists every
installed file, public source revisions, license locations and byte hashes.

- `python/`: gdsfactory SKY130 package; add this directory to the Python path.
- `klayout/`: the selected DRC and LVS decks.
- `sky130A/libs.tech/magic/`: the qualified open_pdks technology/startup files.
- `sky130A/libs.tech/netgen/`: the original preprocessed SKY130A comparison setup.
- `sky130A/libs.tech/combined/continuous/`: the continuous SPICE models.
- `sky130A/libs.tech/ngspice/` and model-only files under `libs.ref/`: the separate
  binned SPICE model set. Both sets retain their complete recursive include
  closures across declared corners. Use the entry selected by each task.
- `docs/skywater-pdk/`: upstream process/device reference RST, tables and figures.
- `docs/DEVICE_API.md`: installed software API notes, separate from process rules.

Only Magic's two build-machine fallback paths are relocated to the fixed runtime
prefix. Technology, model and deck algorithms are unchanged. `setup.tcl` is an
identical regular-file alias of `sky130A_setup.tcl` for portable packaging.

This is the selected analog runtime subset, not a complete digital PDK install.
Optional standard-cell MAG search paths remain in Magic's upstream startup file;
those cell libraries are not needed by the GDS-ingestion analog extraction flow.
The selected DRC deck does not establish full foundry signoff or silicon validity.
Process reference documents and installed tool-specific implementations have
separate pinned revisions; use task-selected model entry points.
