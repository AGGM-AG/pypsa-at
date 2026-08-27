# Rail Electricity Load Profile (EU)

`electricity for rail` currently inherits the shape of the measured ENTSO-E base load
(see `mods/demand/electricity.py`, `base_load_load_splitting`). That is a deliberate
simplification: the split preserves the total, but every sectoral component gets the
same profile. Rail traction has a distinctly different shape — a much deeper night
trough, sharper commuter peaks and a freight-driven night base — so this page collects
what is available for a rail-specific profile and documents the placeholder shipped in
`data/pypsa-at/rail_electricity_load_profile_eu.csv`.

## Data availability

There is no published, EU-wide, rail-specific hourly load profile. Even the European
Commission's own METIS model derives its transport time series from German road-traffic
counting statistics (BASt) and applies that weekly profile to all countries and all
transport modes, rail included, explicitly for lack of a Europe-wide transport profile
dataset.

Measured sources that do exist are national and mostly not open:

| Source | Coverage | Resolution | Access |
|---|---|---|---|
| [DB Energie 16.7 Hz Netzzugang](https://www.dbenergie.de/dbenergie-de/netzbetreiber/bahnstromnetz/downloads-netzzugang-bahnstrom) | German traction grid (~10 TWh/a) | quarter-hourly | Not published as a time series; the annual [Hochlastzeitfenster](https://www.dbenergie.de/dbenergie-de/16-7-Hz-Hochlastzeitfenster-4571176) documents the peak windows only |
| [ÖBB-Infrastruktur traction current](https://infrastruktur.oebb.at/en/partners/power-supply/traction-current) | Austrian 16.7 Hz grid, 7 converters | quarter-hourly | Not public; SNNB documents the tariff structure |
| [SBB traction power / load management](https://company.sbb.ch/en/sbb-as-business-partner/services-rus/energy/load-management.html) | Swiss traction grid | quarter-hourly | Not published; the load-management pages describe the shape qualitatively |
| [RTE / ODRÉ open data](https://odre.opendatasoft.com/) | France, transport sector (~94 % rail) | half-hourly / hourly | Open, but the sector aggregate mixes traction and other transport |
| [DemandRegio branch load profiles](https://www.ffe.de/wp-content/uploads/2020/10/DemandRegio_Abschlussbericht.pdf) | Germany, WZ 49 "Landverkehr" | hourly, 2009–2018 | Open via the FfE Open Data API — WZ 49 covers rail *and* road land transport |

Note that the workflow already consumes the FfE Open Data API for industry profiles
(`retrieve_ffe_industry_load_profiles`, `id_opendata=59`). If a suitable land-transport
profile is available under another `id_opendata`, it can be wired in the same way and
should be preferred over the synthetic table below.

## The shipped placeholder profile

`data/pypsa-at/rail_electricity_load_profile_eu.csv` is a **synthetic** profile. It is
not measured data. It reproduces the characteristics that the sources above describe
qualitatively, and is meant as a transparent, reviewable stand-in until measured data
is licensed.

The file is a long-form factor table with three components:

| `component` | Rows | Meaning |
|---|---|---|
| `hour_of_day` | 3 day types × 24 h | Shape within the day, normalized to a daily mean of 1 |
| `day_type` | 3 | Daily energy of Saturday / Sunday relative to a working day |
| `month` | 12 | Seasonal factor, normalized so the calendar-year mean is 1 |

The hourly profile is the product of the three factors, renormalized over the model
snapshots:

```python
import pandas as pd

t = pd.read_csv("data/pypsa-at/rail_electricity_load_profile_eu.csv")
hod = (
    t.query("component == 'hour_of_day'")
    .astype({"index": int})
    .set_index(["day_type", "index"])["factor"]
)
dtw = t.query("component == 'day_type'").set_index("day_type")["factor"]
mon = t.query("component == 'month'").astype({"index": int}).set_index("index")["factor"]

day_type = pd.Series("weekday", index=snapshots)
day_type[snapshots.dayofweek == 5] = "saturday"
day_type[snapshots.dayofweek == 6] = "sunday"

profile = pd.Series(
    hod.reindex(list(zip(day_type, snapshots.hour))).to_numpy()
    * dtw.reindex(day_type).to_numpy()
    * mon.reindex(snapshots.month).to_numpy(),
    index=snapshots,
)
profile /= profile.mean()  # preserves the annual energy of the Load
```

### Assumptions behind the numbers

- **Daily shape.** Clock-face timetables make traction demand step up after the full and
  half hour; the aggregate national shape is a commuter double peak at ~07:00 and
  ~17:00. The morning peak is taken as the annual maximum.
- **Night base.** Rail keeps a substantially higher night base than road transport
  because freight runs at night and rolling stock is pre-heated. The weekday trough is
  ~33 % of the weekday peak.
- **Weekend.** Saturday is set to 82 %, Sunday to 72 % of a working day's energy, with
  flatter shapes, a later morning ramp and a pronounced Sunday-evening return peak.
- **Season.** Winter exceeds summer by ~15 % (train and point heating, lighting, denser
  timetables); August is the annual low from the freight and commuting lull.

Resulting characteristics of the expanded year: annual min/max ratio 0.18, DJF/JJA ratio
1.15, Sunday/weekday ratio 0.72.

### Limitations

- Synthetic — calibrated to qualitative published descriptions, not fitted to measurements.
- One shape for all EU countries. National timetable structures, the freight share and
  the electrification rate differ considerably.
- No holiday calendar. Public holidays behave like Sundays in reality; the table only
  distinguishes weekday / Saturday / Sunday.
- Traction and stationary rail consumption are not separated.
