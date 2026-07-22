import pypsa
import pytest
from evals.statistic import ESMStatistics


@pytest.fixture
def link_network():
    """Two-bus network with a single Link carrying manually set flows."""
    n = pypsa.Network()
    n.set_snapshots([0, 1])
    n.add("Bus", "A", location="A", carrier="AC")
    n.add("Bus", "B", location="B", carrier="AC")
    n.add("Link", "L1", bus0="A", bus1="B", efficiency=0.9, p_nom=100)
    n.links_t.p0["L1"] = [10, -5]
    n.links_t.p1["L1"] = [-8, 6]
    n.statistics = ESMStatistics(n)
    return n


def test_loss_attributes_to_sending_bus_location(link_network):
    """Loss is attributed to the sending port's location, per snapshot."""
    result = link_network.statistics.loss(
        groupby=["location", "carrier", "bus_carrier"], drop_zero=False
    )

    assert list(result.columns) == [0, 1]
    assert result.loc[("Link", "A", "", "AC"), 0] == 2
    assert result.loc[("Link", "B", "", "AC"), 1] == 1
    # the receiving port contributes no loss for that snapshot
    assert result.loc[("Link", "A", "", "AC"), 1] == 0
    assert result.loc[("Link", "B", "", "AC"), 0] == 0


@pytest.fixture
def line_network():
    """Two-bus network with a single Link carrying manually set flows."""
    n = pypsa.Network()
    n.set_snapshots([0, 1])
    n.add("Bus", "A", location="A", carrier="AC", v_nom=380)
    n.add("Bus", "B", location="B", carrier="AC", v_nom=380)
    n.add("Line", "L1", bus0="A", bus1="B", x=0.1, r=0.01, s_nom=100)
    n.lines_t.p0["L1"] = [10, -9]  # A -> B, then B -> A
    n.lines_t.p1["L1"] = [-9, 10]
    n.statistics = ESMStatistics(n)
    return n


def test_loss_with_line_flow_reversing_direction(line_network):
    """
    Loss is correctly attributed when a line reverses flow direction.

    At t=0 power flows from A to B, at t=1 it flows from B to A. In both
    cases the loss should be attributed to the sending side's location.
    """
    result = line_network.statistics.loss(
        groupby=["location", "carrier", "bus_carrier"], drop_zero=False
    )

    assert result.loc[("Line", "A", "", "AC"), 0] == 1
    assert result.loc[("Line", "A", "", "AC"), 1] == 0
    assert result.loc[("Line", "B", "", "AC"), 0] == 0
    assert result.loc[("Line", "B", "", "AC"), 1] == 1
