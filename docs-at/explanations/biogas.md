# Biogas-to-gas and Biogas-to-power costs

Biogas in PyPSA-AT is modeled as a primary energy carrier, derived directly from spatially distributed supply potentials (from JRC ENSPRESO data). 
Biogas is not produced in the model from other energy carriers and is distinct from the biomass feedstocks that are also introduced via potentials.
Biogas Generator components are added via conversion of input data for "wet biomass" from the ENSPRESO dataset. This conversion is not modeled via PyPSA components, but converted from the potentials.

From the **biogas Bus**, two conversion pathways are possible. They are also depicted in the below figure. 

![Biogas-to-gas and biogas-to-power cost pathways](../assets/figure-biogas-to-gas-to-power-costs.png){ width="600" }


### 1) Biogas-to-gas --> gas-to-power 
- Component: Link (biogas Bus -> gas Bus) 
- extendable 

#### Biogas-to-gas cost structure
Biogas-to-gas costs are made up of biogas (plant) capital cost plus biogas upgrading capital costs. 
The data is extracted from `pypsa/technology-data` via `DEA data sheets for renewable fuels` (Sheet 4.1 "Upgrading 3,000 Nm3 per h"). This dataset in technology-data was last updated in January 2024, while a new version is available at the DEA itself: [DEA data sheets for renewable fuels 2026](https://ens.dk/en/analyses-and-statistics/technology-data-renewable-fuels). 

| Total costs   | cost structure                                                | Value (2024)                     | Unit    |
| ------------- | ------------------------------------------------------------- | -------------------------------- | ------- |
| capital cost  | biogas capital cost<br>+ biogas upgrading capital cost        | 189019 <br>+ 54335<br>= 243354   | Eur/MW  |
| marginal cost | biogas upgrading VOM                                          | 4.4251                           | Eur/MWh |

### 2) Biogas-to-power 
- Component: Link (biogas Bus -> AC Bus) 
- non-extendable (existing brownfield only) by design

#### Biogas-to-power cost structure
For biogas-to-power, the costs depend on the costs of the biomass CHP capital or investment cost, multiplied by the efficiency of the CHP. 
Note: solid biomass CHP is indeed used in this link, even though it represents biogas-to-power. The efficiency values are deemed sufficiently similar to allow this abbreviation. This may be changed in future iterations of PyPSA-AT for more clarity. 
The data is extracted from `pypsa/technology-data` via `DEA technology data for el and dh`, sheet "09a Wood Chips, Large 50 Degree", using a large wood chip CHP plant. This value is then modified in `add_existing_baseyear.py:522-523`) "EOP from technology-data seems to be somewhat too efficient". 

| Total costs   | cost structure                                                                       | Value (2024)                        | Unit      |
| ------------- |--------------------------------------------------------------------------------------|-------------------------------------|-----------|
| capital cost  | central solid biomass CHP capital cost<br>*  central solid biomass CHP efficiency    | 418978 <br>* 0.2694 <br>= 112872.7  | Eur/MW    |
| marginal cost | central solid biomass VOM                                                            | 4.8795                              | Eur/MWh_e |




