import pytest
from glayout import sky130
from glayout.blocks.elementary.current_mirror.current_mirror import (current_mirror, current_mirror_interdigitized_netlist)

def test_interdigitized_current_mirror_netlist():
    """
    Regression test:
    - Interdigitized current mirror netlist is created
    - two_trans_interdigitized subckt is instantiated
    - Correct top-level nodes exist
    """

    nl = current_mirror_interdigitized_netlist(
        pdk=sky130,
        width=3,
        length=0.15,
        fingers=1,
        multipliers=3,
        with_dummy=True,
        device="nfet",
    )

    spice = nl.generate_netlist()

    # Top-level subckt
    assert ".subckt CMIRROR" in spice

    # Interdigitized primitive must be present
    assert "two_trans_interdigitized" in spice

    # Node sanity
    for node in ["VREF", "VOUT", "VSS", "B"]:
        assert node in spice


def test_interdigitized_current_mirror_layout(tmp_path):
    """
    Regression test:
    - Layout instantiates without error
    - Ports exist
    - GDS can be written
    """

    comp = current_mirror(
        pdk=sky130,
        numcols=3,
        device="nfet",
        width=3,
        length=0.15,
        with_dummy=True,
        with_tie=True,
    )

    # Component sanity
    assert comp is not None
    assert "netlist" in comp.info

    # Required ports should exist
    port_names = comp.ports.keys()
    assert any("A_source" in p or "source" in p for p in port_names)
    assert any("A_drain" in p or "drain" in p for p in port_names)

    # GDS write regression
    gds_path = tmp_path / "current_mirror.gds"
    comp.write_gds(gds_path)

    assert gds_path.exists()
    assert gds_path.stat().st_size > 0
