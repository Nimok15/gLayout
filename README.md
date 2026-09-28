# Glayout

A PDK-agnostic layout automation framework for analog circuit design.

## Overview

gLayout is an open-source Python framework for generating analog layouts. Transistors, placement and routing are defined in code, and gLayout turns each cell into a GDS file built to be DRC-clean for the target PDK. No design rules are hard-coded; gLayout reads them from the active PDK at build time. As a result, a single generator produces layouts for every supported PDK, currently SkyWater 130 (sky130) and GlobalFoundries 180 (gf180). 

## How it works

Most analog layout is still drawn by hand, and much of that work is repetitive. gLayout splits the job into two layers.

### 1. PDK layer (the translator)

- **Universal naming:** Layers get simple names like `met2` or `poly` instead of each factory's own layer numbers.
- **Smart rulebook:** Every spacing and manufacturing rule for each factory is stored in one place, so the layout tool looks rules up instead of using fixed numbers.

### 2. Generator layer (the building blocks)

- **Basic parts:** Transistors, vias (connections between metal layers) and guard rings are built automatically from code.
- **Complex circuits:** Basic parts snap together into bigger blocks like differential pairs and op-amps.
- **Portable designs:** With no factory numbers or fixed measurements in the code, the same design works on every supported process.

### Why this matters

- **Write once:** A cell is written once and reused across processes.
- **Easy resizing:** Changing a size takes one parameter, not a redraw.
- **Automatic checking:** Every layout can be checked for errors automatically.
- **AI-ready:** Because cells are plain code, software and AI models can generate or tune them.

## Requirements

| What | Needed for | Notes |
|---|---|---|
| **Python 3.10 or 3.11** | Everything | Python 3.12+ does not currently work: the pinned `numpy<=1.24` fails to build there. |
| **`PDK_ROOT` environment variable** | Importing `sky130` and `gf180` | Must be set *before* `import glayout`, even if you only generate GDS. See [Troubleshooting](#troubleshooting). |
| **KLayout** | Viewing GDS files, `pdk.drc()` | Installed automatically as a Python package; the desktop app is handy for viewing. |
| **PDK files** (sky130A / gf180mcuD) | DRC, LVS, PEX | Not needed just to generate GDS. |
| **Magic, Netgen, ngspice** | `drc_magic()`, LVS, PEX, simulation | Optional; only for the verification flow. |

**Easiest route:** the [IIC-OSIC-TOOLS Docker image](docs/IIC-OSIC-TOOLS/README.md) ships every EDA tool and both PDKs (sky130A and gf180mcuD) pre-installed. See [docs/gLayout_Install.md](docs/gLayout_Install.md) and [tutorial/HOW_TO_RUN.md](tutorial/HOW_TO_RUN.md) for step-by-step setup.

## Installation

We recommend a virtual environment so gLayout's pinned dependencies (gdsfactory 7.x, numpy 1.x) don't clash with other projects:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### Basic Installation

```bash
pip install .
```

### Development Installation

```bash
git clone https://github.com/your-username/glayout.git
cd glayout
pip install -e ".[dev]"
```

### ML Features Installation

```bash
pip install -e ".[ml]"
```

### LLM Features Installation

```bash
pip install -e ".[llm]"
```

### Set up the environment

```bash
export PDK_ROOT=/path/to/your/pdks   
export PDK=sky130A                       # or gf180mcuD             
```

### Check that it worked

```bash
python -c "from glayout import sky130, gf180; print('sky130:', sky130 is not None, '| gf180:', gf180 is not None)"
```

## Quick start

### Build a single part

```python
from glayout import sky130, gf180, nmos, via_stack

# A via stack from metal 2 up to metal 3
via = via_stack(sky130, "met2", "met3", centered=True)
via.write_gds("via.gds")

# An NMOS transistor with 2 fingers: 1 µm wide, 0.15 µm long
fet = nmos(sky130, width=1.0, length=0.15, fingers=2)
fet.write_gds("nmos.gds")

# The same transistor on a different process
fet_gf = nmos(gf180, width=1.0, fingers=2)
```

- The first argument is always the process (`sky130` or `gf180`).
- If `length` is left out, the smallest length the process allows is used.

### Place and connect parts

```python
from glayout import gf180, nmos, c_route, movex, evaluate_bbox
from glayout.backend import Component

pdk = gf180
top = Component("mirror_sketch")

# Add two transistors
ref = top << nmos(pdk, width=3, fingers=2)
out = top << nmos(pdk, width=3, fingers=2)

# Move the second one to the right, at a safe distance
movex(out, evaluate_bbox(ref)[0] + pdk.util_max_metal_seperation())

# Connect the two gates with a wire
top << c_route(pdk, ref.ports["multiplier_0_gate_E"], out.ports["multiplier_0_gate_E"])

top.write_gds("mirror_sketch.gds")
```

### Check the layout

```python
pdk.drc(top, "drc_out/")   # Returns True if the layout passes all rules
```

- This needs KLayout and the PDK installed.

## Tutorials

Jupyter notebooks in [`tutorial/`](tutorial/README.md). Suggested order for newcomers:

| # | Notebook | PDK | You'll learn |
|---|---|---|---|
| 1 | [Introduction to gLayout](tutorial/GLayout_Introduction.ipynb) | sky130 + gf180 | Core concepts and workflow |
| 2 | [Via placement](tutorial/GLayout_Via.ipynb) | sky130 + gf180 | Vias and metal layers |
| 3 | [Current mirror](tutorial/GLayout_Cmirror.ipynb) | sky130 + gf180 | Placing and routing a real cell |
| 4 | [FVF part 1](tutorial/glayout_tutorial_FVF_part1.ipynb) → [part 2](tutorial/glayout_tutorial_FVF_part2.ipynb) | gf180 | Placement, routing, DRC, then LVS, PEX and simulation |
| 5 | [Inverter part 1](tutorial/glayout_tutorial_INV_part1.ipynb) | gf180 | A second end-to-end example |
| 6 | [Available cells](tutorial/GLayout_Cells.ipynb) · [Op-amp](tutorial/glayout_opamp.ipynb) | gf180 · sky130 | The built-in cell library and a full op-amp |

[tutorial/HOW_TO_RUN.md](tutorial/HOW_TO_RUN.md) lists which tools and PDK each notebook needs.

## Features

### PDK Agnostic Layout
- Generic layer mapping
- Technology-independent design rules
- Support for multiple PDKs (sky130, gf180)

### Basic parts
- **Transistors:** `nmos`, `pmos`, and the lower-level `multiplier`
- **Vias:** `via_stack`, `via_array`
- **Guard rings:** `tapring`
- **Capacitors:** `mimcap`, `mimcap_array`
- **Resistors:** `resistor`

### Ready-made cells (`glayout.cells`)
- **Elementary:** `current_mirror`, `diff_pair`, `flipped_voltage_follower`, `transmission_gate`
- **Composite:** `opamp`, `diff_pair_ibias`, `low_voltage_cmirror`, `stacked_nfet_current_mirror`, `differential_to_single_ended_converter`

### Routing tools
- **`straight_route`**: a direct straight wire
- **`L_route`**: a wire with one bend
- **`c_route`**: a wire that goes out, across and back, shaped like a C
- **`smart_route`**: picks the right route shape automatically

### Checking tools
- **DRC (Design Rule Check):** confirms the layout follows the factory's rules. Run with `pdk.drc()` (KLayout) or `pdk.drc_magic()` (Magic).
- **LVS (Layout vs. Schematic):** confirms the layout matches the intended circuit. Run with `pdk.lvs_netgen()` (Netgen).
- **Parasitic extraction:** estimates the unwanted resistance and capacitance of the wiring, using Magic.

### Natural Language Processing/Large Language Model Framework
- Convert natural language descriptions to layouts
- Support for standard components
- Custom component definitions

### Supported Open Source PDKs
- SkyWater [SKY-130A](https://skywater-pdk.readthedocs.io/en/main/)
- GlobalFoundries [GF-180mcuD](https://gf180mcu-pdk.readthedocs.io/en/latest/)

## Two backends

A backend is the library that draws the actual shapes. gLayout supports two:

- **gdsfactory** (default): the original backend.
- **gdstk**: newer, and roughly 10–25× faster in the test suite's timing runs. It is planned to become the default.

Switch between them with one setting:

```bash
export GLAYOUT_BACKEND=gdstk    # or gdsfactory
```

## Documentation

For detailed documentation, please visit our [documentation site](https://glayout.readthedocs.io/).

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/contributor_guide.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Citation

If you use Glayout in your research, please cite our papers:

```bibtex
@article{hammoud2024human,
  title={Human Language to Analog Layout Using Glayout Layout Automation Framework},
  author={Hammoud, A. and Goyal, C. and Pathen, S. and Dai, A. and Li, A. and Kielian, G. and Saligane, M.},
  journal={Accepted at MLCAD},
  year={2024}
}

@article{hammoud2024reinforcement,
  title={Reinforcement Learning-Enhanced Cloud-Based Open Source Analog Circuit Generator for Standard and Cryogenic Temperatures in 130-nm and 180-nm OpenPDKs},
  author={Hammoud, A. and Li, A. and Tripathi, A. and Tian, W. and Khandeparkar, H. and Wans, R. and Kielian, G. and Murmann, B. and Sylvester, D. and Saligane, M.},
  journal={Accepted at ICCAD},
  year={2024}
}
```

## Contact

For questions and support, please contact:
- Email: mehdi_saligane@brown.edu
 
