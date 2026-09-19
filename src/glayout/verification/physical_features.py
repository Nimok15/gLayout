"""Physical feature extraction for glayout layouts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

try: 
    import gdstk
except ImportError as _exc:  
    raise ImportError("physical_features requires gdstk") from _exc

from glayout.backend import Component

SCHEMA_VERSION = "2.0.0"

_RUN_PEX_SCRIPT = Path(__file__).parent / "run_pex.sh"

DEFAULT_SYMMETRY_LAYERS: Optional[Sequence[tuple[int, int]]] = None  

_NUM_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)$")

_MULT = {
    "t": 1e12, "g": 1e9, "k": 1e3, "x": 1e6,
    "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18,
}


_UNIT_WORDS = ("farads", "farad", "ohms", "ohm", "henries", "henry")


def parse_spice_value(token: str) -> Optional[float]:
    """Parse a SPICE numeric token to a float in base units.

    Returns None if the token is not a number, so callers can count misses
    rather than silently treating them as zero.

    >>> parse_spice_value("0.24fF")
    2.4e-16
    >>> parse_spice_value("2.3p")
    2.3e-12
    >>> parse_spice_value("1.5meg")
    1500000.0
    """
    m = _NUM_RE.match(token.strip())
    if not m:
        return None
    mantissa = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return mantissa

    if suffix.startswith("meg"):
        return mantissa * 1e6

    for unit in _UNIT_WORDS:
        if suffix.endswith(unit):
            stem = suffix[: -len(unit)]
            if stem == "":
                return mantissa 
            if stem.startswith("meg"):
                return mantissa * 1e6
            if stem[0] in _MULT:
                return mantissa * _MULT[stem[0]]
            break

    if suffix[0] in _MULT:
        return mantissa * _MULT[suffix[0]]
    return None


def parse_parasitics(pex_spice_path: Path) -> dict[str, Any]:
    """Accumulate parasitic R and C from a magic ext2spice netlist.

    Per-net capacitance is the signal that matters: the same total C is a very
    different circuit depending on whether it lands on a high-impedance node or
    a supply rail. A capacitor between two nets loads both, so it is credited
    to each.
    """
    result: dict[str, Any] = {
        "total_resistance_ohms": None,
        "total_capacitance_farads": None,
        "n_resistors": 0,
        "n_capacitors": 0,
        "n_parse_failures": 0,
        "per_net_capacitance_farads": {},
        "max_net_capacitance_farads": None,
        "max_net_capacitance_net": None,
    }

    if not pex_spice_path.exists() or pex_spice_path.stat().st_size == 0:
        return result

    total_r = 0.0
    total_c = 0.0
    per_net_c: dict[str, float] = defaultdict(float)
    failures = 0

    with pex_spice_path.open("r", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue

            if line[0] in "*.+$":
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            kind = parts[0][0].upper()
            if kind not in ("R", "C"):
                continue

            value = parse_spice_value(parts[3])
            if value is None:
                failures += 1
                continue

            if kind == "R":
                total_r += value
                result["n_resistors"] += 1
            else:
                total_c += value
                result["n_capacitors"] += 1
                for net in (parts[1], parts[2]):
                    per_net_c[net] += value

    result["total_resistance_ohms"] = total_r
    result["total_capacitance_farads"] = total_c
    result["n_parse_failures"] = failures
    result["per_net_capacitance_farads"] = dict(per_net_c)

    if per_net_c:
        worst = max(per_net_c.items(), key=lambda kv: kv[1])
        result["max_net_capacitance_net"] = worst[0]
        result["max_net_capacitance_farads"] = worst[1]

    return result


def _polygons_by_layer(component: Component) -> dict[tuple[int, int], list[np.ndarray]]:
    """Return {(layer, datatype): [vertex arrays]} for a flattened component."""
    polys = component.get_polygons(by_spec=True)
    if isinstance(polys, dict):
        return {tuple(k): [np.asarray(p) for p in v] for k, v in polys.items()}
    # Defensive: some backends return a flat list. Score it as one pseudo-layer
    # and flag it, rather than silently producing a flattened-layer score.
    return {(-1, -1): [np.asarray(p) for p in polys]}


def _to_gdstk(vertex_arrays: Iterable[np.ndarray]) -> list["gdstk.Polygon"]:
    return [gdstk.Polygon(v) for v in vertex_arrays if len(v) >= 3]


def _merged_area(polys: Sequence["gdstk.Polygon"]) -> float:
    """True geometric area of the union. gdstk Cell.area() does NOT merge."""
    if not polys:
        return 0.0
    merged = gdstk.boolean(list(polys), [], "or")
    return float(sum(p.area() for p in merged))


def _mirror_polys(
    polys: Sequence["gdstk.Polygon"], axis: str, cx: float, cy: float
) -> list["gdstk.Polygon"]:
    """Reflect about the component's own centre, not the global origin."""
    out = []
    for p in polys:
        q = p.copy()
        if axis == "vertical":     
            q.scale(-1, 1, (cx, cy))
        else:                      
            q.scale(1, -1, (cx, cy))
        out.append(q)
    return out


def calculate_areas(component: Component) -> dict[str, Optional[float]]:
    """Both area definitions, named so they cannot be confused.

    ``polygon_area_um2`` is gdstk's unmerged per-layer sum (overlapping shapes
    double-count). ``bbox_area_um2`` is the silicon footprint and is the one
    comparable to area figures reported in the literature.
    """
    try:
        (x0, y0), (x1, y1) = np.asarray(component.bbox)
        bbox_area = float((x1 - x0) * (y1 - y0))
    except Exception:
        bbox_area = None

    try:
        polygon_area = float(component.area())
    except Exception:
        polygon_area = None

    merged_area = None
    try:
        by_layer = _polygons_by_layer(component)
        merged_area = float(
            sum(_merged_area(_to_gdstk(v)) for v in by_layer.values())
        )
    except Exception:
        pass

    return {
        "bbox_area_um2": bbox_area,
        "polygon_area_um2": polygon_area,
        "merged_polygon_area_um2": merged_area,
    }


def calculate_symmetry_scores(
    component: Component,
    layers: Optional[Sequence[tuple[int, int]]] = None,
) -> dict[str, Any]:
    """Per-layer symmetry, scored on [0, 1].

    For a region A and its mirror A', the XOR area is 2|A| - 2|A n A'|, so
    1 - xor / (2|A|) equals |A n A'| / |A| -- the fraction of the layer that
    maps onto itself. 1.0 is perfect symmetry, 0.0 is fully disjoint.

    Layers are scored independently. Flattening them together (as the previous
    implementation did) hides any asymmetry contained within a lower layer's
    footprint, which is most routing asymmetry in a real analog cell.
    """
    out: dict[str, Any] = {
        "per_layer": {},
        "symmetry_horizontal": None,
        "symmetry_vertical": None,
        "symmetry_min": None,
        "weighted_by": "merged_layer_area",
        "flattened_fallback": False,
    }

    try:
        by_layer = _polygons_by_layer(component)
    except Exception:
        return out

    if (-1, -1) in by_layer:
        out["flattened_fallback"] = True

    try:
        (x0, y0), (x1, y1) = np.asarray(component.bbox)
    except Exception:
        return out
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    tot_w = 0.0
    acc_h = 0.0
    acc_v = 0.0

    for spec, vertex_arrays in sorted(by_layer.items()):
        if layers is not None and tuple(spec) not in set(map(tuple, layers)):
            continue
        polys = _to_gdstk(vertex_arrays)
        if not polys:
            continue
        area = _merged_area(polys)
        if area <= 0:
            continue

        scores = {}
        for axis, key in (("vertical", "horizontal"), ("horizontal", "vertical")):
            mirrored = _mirror_polys(polys, axis, cx, cy)
            xor = gdstk.boolean(list(polys), mirrored, "xor")
            xor_area = float(sum(p.area() for p in xor))
            scores[key] = max(0.0, min(1.0, 1.0 - xor_area / (2.0 * area)))

        key = f"{spec[0]}/{spec[1]}"
        out["per_layer"][key] = {
            "area_um2": area,
            "symmetry_horizontal": scores["horizontal"],
            "symmetry_vertical": scores["vertical"],
        }
        acc_h += scores["horizontal"] * area
        acc_v += scores["vertical"] * area
        tot_w += area

    if tot_w > 0:
        out["symmetry_horizontal"] = acc_h / tot_w
        out["symmetry_vertical"] = acc_v / tot_w
        out["symmetry_min"] = min(
            min(v["symmetry_horizontal"], v["symmetry_vertical"])
            for v in out["per_layer"].values()
        )
    return out

def resolve_magicrc(pdk_name: str = "sky130A", pdk_root: Optional[str] = None) -> Path:
    """Locate the magicrc for a PDK. Never hardcode sky130A."""
    root = Path(pdk_root or os.environ.get("PDK_ROOT", ""))
    if not root:
        raise EnvironmentError("PDK_ROOT is not set and pdk_root was not given")
    return root / pdk_name / "libs.tech" / "magic" / f"{pdk_name}.magicrc"


def run_pex(
    gds_path: str | Path,
    cell_name: str,
    work_dir: str | Path,
    pdk_name: str = "sky130A",
    timeout_s: float = 900.0,
    extresist: bool = True,
) -> dict[str, Any]:
    """Run magic extraction into ``work_dir``.

    Success is decided by the presence of a non-empty output netlist, not by
    the exit code: magic frequently exits 0 after failing to extract.
    """
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / f"{cell_name}_pex.spice"
    if out_path.exists():
        out_path.unlink()

    info: dict[str, Any] = {
        "status": "not run",
        "pex_netlist_path": str(out_path),
        "returncode": None,
        "wall_time_s": None,
        "stderr_tail": None,
    }

    if not _RUN_PEX_SCRIPT.exists():
        info["status"] = f"error: run_pex.sh not found at {_RUN_PEX_SCRIPT}"
        return info

    try:
        magicrc = resolve_magicrc(pdk_name)
    except EnvironmentError as exc:
        info["status"] = f"error: {exc}"
        return info
    if not magicrc.exists():
        info["status"] = f"error: magicrc not found at {magicrc}"
        return info

    gds_abs = str(Path(gds_path).resolve())
    started = time.time()
    try:

        proc = subprocess.run(
            ["bash", str(_RUN_PEX_SCRIPT), gds_abs, cell_name, str(magicrc),
             "extresist" if extresist else "noextresist"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        info["returncode"] = proc.returncode
        info["stderr_tail"] = (proc.stderr or "")[-2000:] or None
    except subprocess.TimeoutExpired:
        info["status"] = "timeout"
        info["wall_time_s"] = time.time() - started
        return info
    except Exception as exc:  
        info["status"] = f"error: {exc}"
        info["wall_time_s"] = time.time() - started
        return info

    info["wall_time_s"] = time.time() - started
    if out_path.exists() and out_path.stat().st_size > 0:
        info["status"] = "ok"
    else:
        info["status"] = f"failed: no output netlist (rc={proc.returncode})"
    return info


def run_physical_feature_extraction(
    gds_path: str | Path,
    cell_name: str,
    top_level: Component,
    work_dir: str | Path,
    pdk_name: str = "sky130A",
    pex_timeout_s: float = 900.0,
    do_pex: bool = True,
    symmetry_layers: Optional[Sequence[tuple[int, int]]] = DEFAULT_SYMMETRY_LAYERS,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    """Extract parasitics and geometry for one layout.

    Every path is resolved against ``work_dir``, so concurrent workers on the
    same cell name are isolated. Give each variant its own directory.
    """
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "cell_name": cell_name,
        "pdk_name": pdk_name,
        "work_dir": str(work_dir),
        "pex": {"status": "skipped" if not do_pex else "not run"},
        "parasitics": {},
        "geometric": {},
        "timing_s": {},
    }


    if do_pex:
        pex_info = run_pex(gds_path, cell_name, work_dir, pdk_name, pex_timeout_s)
        results["pex"] = pex_info
        results["timing_s"]["pex"] = pex_info.get("wall_time_s")
        if pex_info["status"] == "ok":
            t0 = time.time()
            results["parasitics"] = parse_parasitics(Path(pex_info["pex_netlist_path"]))
            results["timing_s"]["parse_parasitics"] = time.time() - t0
        else:
            results["parasitics"] = parse_parasitics(Path("/nonexistent"))


    t0 = time.time()
    try:
        results["geometric"].update(calculate_areas(top_level))
    except Exception as exc:  # noqa: BLE001
        results["geometric"]["area_error"] = str(exc)
    results["timing_s"]["area"] = time.time() - t0

    t0 = time.time()
    try:
        results["geometric"]["symmetry"] = calculate_symmetry_scores(
            top_level, layers=symmetry_layers
        )
    except Exception as exc:  # noqa: BLE001
        results["geometric"]["symmetry"] = {"error": str(exc)}
    results["timing_s"]["symmetry"] = time.time() - t0

    if not keep_intermediates:
        for pattern in ("*.ext", "*.res.ext", "*.nodes", "*.sim", "*.al"):
            for stale in work_dir.glob(pattern):
                try:
                    stale.unlink()
                except OSError:
                    pass

    return results
