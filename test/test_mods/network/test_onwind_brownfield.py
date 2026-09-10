import numpy as np
import pandas as pd


def test_onwind_brownfield_capacity(nc):
    """The fixed Austrian onshore-wind capacity matches the prepared vintages."""
    for year, network in nc.networks.items():
        year = int(year)
        brownfield = pd.DataFrame.from_dict(
            network.meta["resources"]["onwind_brownfield"]
        )
        lifetime = network.generators.loc[
            network.generators.carrier.eq("onwind"), "lifetime"
        ].iloc[0]
        expected = brownfield[
            brownfield.year.add(lifetime).gt(year) & (brownfield.capacity > 0)
        ]

        base_year = min([int(year) for year in nc.networks.keys()])
        at_onwind = network.generators.query(
            "(carrier == 'onwind') & index.str.startswith('AT')"
        )

        merge = expected.merge(
            at_onwind.reset_index(),
            right_on=["bus", "build_year"],
            left_on=["region", "year"],
            how="outer",
        )

        missing_components = merge[merge.name.isna()]
        missing_brownfield = merge[
            merge.name.notna() & merge.region.isna() & (merge.build_year < base_year)
        ].set_index("name")
        base_year_components = merge[
            merge.region.notna() & merge.name.notna() & (merge.build_year == base_year)
        ].set_index("name")
        other_components = merge[
            merge.region.notna() & merge.name.notna() & (merge.build_year < base_year)
        ].set_index("name")

        assert len(missing_components) == 0
        assert (missing_brownfield.p_nom_opt == 0).all()
        assert (base_year_components.p_nom_opt >= base_year_components.capacity).all()
        assert np.allclose(other_components.p_nom_opt, other_components.capacity)
