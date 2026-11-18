# License scope

The default license for original AnalogLayoutWorld material is **Apache-2.0**.
The complete text is in [LICENSE](LICENSE). This default covers the original
software, documentation, configuration, annotations and circuit designs
distributed in this repository.

Third-party material and adaptations retain the applicable upstream terms.
File-specific notices and the exceptions below take precedence over the project
default. The root license does not relicense third-party circuits, datasets,
process files, or software installed in the EDA image.

## Third-party exceptions

| Material | Applicable upstream terms |
|---|---|
| Content from the 31 Analog Design Bench tasks, including adapted instructions, netlists and non-software fixtures | CC-BY-NC-4.0; preserve attribution and modification records. Upstream software remains Apache-2.0 under its own scope notice. |
| Selected LOADBench circuits and source content in the three LOADBench tasks | CC-BY-4.0; preserve attribution and the recorded design-point/adaptation information. |
| The two AJC-derived source subcircuits | Apache-2.0; preserve original notices. |
| Vendored PCells, PDK models, process documentation, DRC/LVS and Magic/Netgen technology files | Their individual MIT, Apache, GPL and open_pdks terms, recorded in the PDK asset manifest and retained license texts. |
| Software installed into the EDA image | Each software component's original license, retained in the image and source provenance. |

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md),
`configs/paper-v1/sources.json`, `LICENSES/`, and
`docker/pdk/sky130/asset-manifest.json` for the source mapping and full texts.
The project default does not remove the ADB content's non-commercial condition;
this repository does not grant blanket commercial rights over all 40 tasks.

## Mixed directories and distributions

`tasks/*/tests/tools/` contains copies of the canonical verifier, parameters,
annotations and the adapted LVS asset. Each copy retains the scope and notices
of its original file; it does not inherit a single license from the surrounding
task. Source software and adjacent non-software test fixtures can have different
terms.

The Python wheel includes this scope statement, the project license and the
applicable third-party notices and texts. Its contents do not include the task
environment directories or vendored PDK. Licensing does not depend solely on a
file extension or on whether a file is inside a Python package.

The EDA base image contains software and PDK assets; task images additionally
contain their respective task content. Redistributing a task image must preserve
the corresponding task's upstream conditions as well as the installed software
notices.
