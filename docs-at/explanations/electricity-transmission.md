# electricity transmission

## Default in PyPSA-Eur

The **default** setting for the line capacity expansion of the electricity grid is limited only by the costs of added AC lines and DC links. 

PyPSA-Eur inherently supports either cost or volume limitations, and either optimal or a fixed percentage of expansion.
The time of the expansion limit applies between investment years and will depend on myopic `planning_horizons`.

| Value | Part   | Description                     |
|-------|--------|---------------------------------| 
| v-    | prefix | sets a limit on the line volume | 
| c-    | prefix | sets a limit on the line cost| 
|-opt|suffix|line expansion is optimized according to capital costs| 
|-1.xx|suffix|line expansion will be limited to a maximum of xx %| 

For example: \
The default value 'vopt' only limits transmission expansion via link and line costs. 
The value 'copt' also limits by allocating costs, but in a more detailed way (distinguishes overhead vs underwater sections etc).  
The value 'v1.1' limits the volumetric transmission expansion of the grid by an additional installation of maximum 10% of currently installed lines in the next investment period. 


### What exactly is limited? 
The defaults describe above are `GlobalConstraints`, limiting the expansion of the grid as a whole. 
Additionally, per-line extension limits are possible. They are set in `prepare_network.py` via the `set_line_nom_max()` function. 


----

## In PyPSA-AT 

A theoretically limitless expansion of the electricity grid lines seems highly unlikely. However, official statements hardly specify exact numbers for the complete potential expansion of the grid.
Until better data is available, an educated guess on the potential expansion of the electricity transmission grid has been made at a maximum of 25%. This is a high, but limited upper boundary for the expansion of the grid. In any case, it is more realistic than the default limitless expansion.



To implement this, the following additions were made in the `config.at.yaml`: 


### **scenario:** 
change
```yaml
scenario:
  ll: 
  -vopt 
```
to 
```yaml
scenario: 
  ll: 
  -v1.25 
```

### **electricity:**
change
```yaml
electricity:
  transmission_limit: vopt
```
to
```yaml
electricity:
  transmission_limit: v1.25
```




