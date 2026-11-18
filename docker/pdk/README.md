# Pinned SKY130 runtime resources

[English](README.md) | [简体中文](README.zh-CN.md) · [Documentation](../../docs/README.md)

`sky130/` is the reviewed, vendored resource tree copied into the EDA image at
`/opt/analog-layout/pdks/sky130/`. Normal runs and source image builds use this
checked-in tree directly; no separate PDK preparation is required.

It contains Python PCell source and fixed-cell library GDS, DRC/LVS decks, Magic
technology, Netgen comparison setup, continuous and binned SPICE model include
closures, and offline process/API references. Library GDS files are upstream
components, rather than task submissions. See [runtime scope](sky130/README.md).

## Verify the resources

From the checkout root, check the packaged file set and selected resource hashes:

```bash
python3 docker/pdk/verify.py
python3 -m unittest discover -s tests -p test_pdk_assets.py
```

Inside the EDA image, check the installed tree with:

```bash
python -I -B /opt/analog-layout/build-checks/verify_pdk.py \
  --root /opt/analog-layout/pdks/sky130
```

These checks validate packaging, not a layout's physical correctness. The manifest
check rejects missing, additional, modified, and symbolic-link files; the tests
also anchor selected qualified resources independently of the manifest.

## Sources and licenses

| Component | Fixed source | Preserved license |
|---|---|---|
| Python PCells and fixed-cell GDS | `gdsfactory/skywater130` at `5c7b9ba5f13b5411e53bbb5e35ed3db4f4e79986` | MIT |
| KLayout decks | `fossi-foundation/sky130_klayout_pdk` at `4ea0975391feacbdac697bf07029d8908d292613` | DRC GPL-3.0; LVS Apache-2.0 |
| Magic technology and Netgen setup | `RTimothyEdwards/open_pdks` at `0ec4fa67eade28cd0a4352c04df981840809427b` | Upstream LICENSE and original file notices |
| Continuous models | Volare release `sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b` | Apache-2.0 headers |
| Binned models | The same Volare release; separate `libs.tech/ngspice` entry and `libs.ref` closure | Apache-2.0 headers |
| Process reference | `google/skywater-pdk` at `7198cf647113f56041e02abf3eb623692820c5e1` | Apache-2.0 |

[asset-manifest.json](sky130/asset-manifest.json) records the files, public source
revisions, source URLs, archive hashes, and license locations. Original headers
and license texts remain in the resource tree. Continuous and binned models have
separate include graphs; use the model entry selected by each task's testbench.

## Optional resource development

For an intentional resource update, inspect the preparation tool's options:

```bash
python3 docker/pdk/prepare.py --help
```

The tool accepts explicit local source paths and a new destination. Replacing
qualified resources requires reviewing the new package; first-time users can use
the checked-in resources and prebuilt EDA image. Image build and correctness
checks are documented in the [EDA image guide](../../docs/images.md).
