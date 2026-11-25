# Methods

All numbers come from `data/parameters.yaml`. Each entry has a unit, a source and a status
(`sourced`, `project`, `illustrative`). Uncertain entries have a pessimistic, central and optimistic value.
Pessimistic means worse for the operator's NPV. The code is in `splash_calc/`.

## 1. Baseline (`baseline.py`, `inputs.py`)

* Consumption is converted to kWh: gas m3 x 10.5 (illustrative, the invoice has the exact value), oil L x 10, MWh x 1000.
* Useful heat `Q_use = sum_c E_c * eta_c` over carriers c. Efficiencies: gas 0.90, oil 0.88, district heat 0.97, other 0.85.
  Boilers older than 20 years get -0.04. An entered boiler efficiency replaces the default for non-district-heat carriers.
* The reported consumption gives the mix of carriers and the plausibility check. The amount of useful heat comes from the
  SPLASH model (section 2). Without a consumption the main heating source is the only carrier, and the data confidence
  score counts the carrier as a default.
* Plausibility: the reported specific heat use is compared with the UBA sample range 513.04 to 5057.61 kWh/(m2 a) (n = 67).
  Values outside the range get a warning.
* Prices: an entered annual cost wins over the default price. Gross or net is respected. VAT counts only when the
  operator cannot deduct it (municipal operation, association, other).

Source: UBA Texte 139/2024, Energieverbrauch von Schwimmbädern.

## 2. Heat demand: the SPLASH model is the basis (`profiles.py`, `splash_engine.py`)

The questionnaire sets the parameters of the SPLASH facility model. The model then computes the hourly heat demand,
and this demand is the single basis of the baseline, the heat pump scenario and the flexible heating scenario.

* **Pool water:** the heat loss of every basin (Delgado Marin and Garcia-Cascales for indoor basins, Buscemi et al. for
  outdoor basins), hourly, from the weather of the zone, the setpoint and the basin geometry.
* **Hall air:** the sensible load `H = S x (T_air - T_ext)`, from the hall floor area and height, the air change rate and the
  heat recovery. Hall floor area comes from the questionnaire. Heat recovery is the SPLASH archetype value.
* **Hot water for showers:** see section 2b. It is part of the model demand when the pool plant heats the shower water.
* **Not in the model:** space heating of other rooms, sauna, catering and the latent (dehumidification) load. They are not calculated.
* **Reported consumption:** it sets only the mix of heat carriers (gas, oil, district heat, other). The amount of useful heat
  is the model demand. The results page compares both and warns if the model is more than 50 % above or more than 33 %
  below the reported useful heat. The hall load rests on assumed geometry and a synthetic occupancy, so a large gap is a
  reason to check the hall area, hall height and heat recovery.
* **Fuel saved:** displaced useful heat divided by the efficiency of the carrier mix, per carrier.

The weather is the SPLASH TMY of the zone (T5 or T6). The demand of the reference year 2025 is the annual basis.

## 2b. Hot water for showers (`splash_engine.py`, `vendor/splash/facility/dhw.py`)

Hot water is proportional to the number of visitors. Per hour:

```
visitors_h = N_h / tau                       N_h persons in the water (occupancy x area, in the season), tau = 1 h
Q_dhw,h   = visitors_h x V x s x rho cp x (T_mix - T_cold,month) x (1 + loss share)
```

`V` is the shower water per visitor (default 50 L, the lower end of 50 to 80 L in VDI 2089 Part 1, 2010 edition read from an excerpt;
the 2023 edition is not checked). `s` is the hot share of the shower water (1.0). `T_mix` is 40 degC, `T_cold` the mains water of the
month (illustrative series, 6.5 to 17 degC), loss share 0. The three values V, T_mix and tau are in `data/parameters.yaml`
(`shower_water_l_per_visitor`, `shower_mix_temp_c`, `stay_in_water_h`); the answer to `r_shower_litres` replaces V.

* **Visitors.** The occupancy profile of the SPLASH package gives the shape over day, week and season. The operator's numbers give the
  level: an annual figure (`q4_visitors_year`) or the daily figures (`q4_visitors_weekday`, `q4_visitors_weekend`) times the open days
  of the week (`q4_days`) times the operating weeks. A missing weekday or weekend value takes the other one. The profile is scaled so
  that a full year sums to the annual visitors. Without any visitor answer the model uses its own occupancy profile (synthetic) and
  the results page says so.
* **Who serves it.** Question `q4_dhw_supply`: `central` (default) means the plant of the pool heats the shower water, so hot water is
  part of the demand, of the design load and of the heater size. `separate` or `none` run the model without hot water.
* **In the hourly model.** Hot water and hall air form one load block, served first and before the basins; under a capacity shortage
  both get the same share. The block COP of the heat pump is the heat-weighted mean of the hall circuit and the hot water circuit
  (sink 60 degC).
* **Design load.** The hot water peak is added in the coincident hour of the design load (instantaneous peak, no averaging), so the heater
  sizes 100, 200 and 300 % of the design load are larger than before. A hot water tank smooths it (next point).
* **Hot water tank.** Question `q4_dhw_tank` (yes or no, only with central hot water), then the size in litres or m³
  (`q4_dhw_tank_size`, `q4_dhw_tank_unit`, 50 L to 100 m³). Heat in the tank = volume x 1.163 kWh/(m³ K) x (60 degC minus the mean mains
  water temperature). Divided by the hot water peak of the model and rounded to whole hours (1 to 12), it is the window over which the shower
  peak is averaged in the design load (`facility.dhw.sizing_smooth_h` of the SPLASH model). The tank therefore lowers the design load and the
  heater size. It does not change the hourly operation, the demand or the heat pump capacity (a quantile of the demand). It is taken as fully
  usable, which is an upper bound. Without a tank, or with `separate` or `none`, the peak is not averaged.
* **Limits.** Showers follow the occupancy and are not concentrated before and after the swim. The hot
  share is 1.0 for every pool type. Sauna visitors are counted only if the operator includes them in the visitor numbers.
* **Calibration.** The optional adaptation to the reported consumption scales basins and hall only. Hot water follows the visitors.

## 3. Heat pump (`heatpump.py`)

* `COP_t = clip(eta_c * (T_sink + 273.15) / max(T_sink - T_source, 5), 1.5, 7)` with `eta_c` = 0.40 / 0.45 / 0.50.
* Sink temperatures: pool water 38 C, hall air 45 C, space heating 45 C, hot water 60 C. Source: outdoor air, ground 10 C or waste heat 15 C.
* The heat pump serves pool water, hall air and space heating. The boiler keeps the peaks. Hot water is served by the heat pump in the rule-based
  operation below (with the hall), and stays with the boiler in the conventional dispatch used as a fallback.
* Capacity: the 0.85 quantile of the served hourly load, or the operator's value.
* Each hour: `heat_t = min(load_t, capacity)`, electricity `= heat / COP` per use.
* Fuel saved = baseline fuel x (heat pump heat / model demand), per carrier. The model demand covers pool water and hall air only.
* **Operation (1.4.1, `hp_rule.py`).** With the SPLASH model available the heat pump runs on the same hourly pool model and
  hysteresis rule as the resistive heater (reference year 2025). Grid electricity holds each basin at its lower limit T_min and
  covers the hall (supply "replace", floor rule). In hours with curtailed power in the zone it charges the basins up to T_max
  with that power. The COP above applies per hour and sink (pool water for basins, hall air for the hall coil). Demand above
  the capacity stays with the existing system and is reported as unmet. Electricity costs grid power at the electricity price and
  curtailed power at the curtailed price; the economics use the resulting average price. CO2 has both views (curtailed power at
  grid mix or at zero). Without the SPLASH model (open-air pools, model error) the earlier conventional dispatch
  (`heat_t = min(load_t, capacity)`) is used.

## 4. Grant (`subsidy.py`)

Grant = 30 % x min(eligible cost, cap). Cap by heated net floor area: 28,000 EUR up to 150 m2, then +197 EUR/m2 (150 to 400),
+118 EUR/m2 (400 to 1000), +79 EUR/m2 above 1000. Example: 500 m2 gives 89,050 EUR. KfW 522 is for companies, 422 for
municipalities. Apply before work starts, there is no legal entitlement, the cap falls from 1 February 2027. Electric
direct heaters are not eligible. Whether the pool hall counts fully needs checking with an energy consultant.

## 5. Flexible heating (`splash_engine.py`, `flexsplash.py`, `vendor/splash`)

The flexible heating scenario runs the SPLASH facility model v1.3 (vendored unchanged in `vendor/splash`; v1.3 adds the hot water of section 2b).

**Pool to model.** Each basin of the questionnaire becomes a SPLASH basin: size class from the basin type
(lap = Schwimmer, teaching = Kurs/Lehr, therapy = Warm/Sprudel/Tret, children = Kleinkind, leisure = Nichtschwimmer or
Wellen/Natur in open-air pools, diving = Sprung/Tauch), environment indoor or outdoor from the pool type, area from length
times width, volume from the known volume or from the depths, perimeter from length and width. The lower temperature limit
is the setpoint of the operator, the upper limit is the setpoint plus the allowed temperature change (question 11). Without
an answer the class band of `data/splash/config/bands.csv` is used. Indoor basins share one hall with the hall area of the
questionnaire (else 2.5 times the water area), archetype Hallenbad or Kombibad, heat recovery as in the SPLASH archetype (0.5 for
the Kombibad) for every ventilation answer. The season comes from the opening and closing dates of the questionnaire (for example 1 May to 30 September) and is rounded to
whole model months: an opening date after the 15th starts in the next month, a closing date before the 15th ends in the previous
month. A season over the new year is allowed. Open-air pools without an answer get a default of about 21 weeks around July.
In combined pools each basin carries a location (indoor or outdoor). The halls run all year and the season is the opening window of the outdoor basins (question `q4_season_outdoor`, default May to September). Open days and operating weeks give the annual visitors for the hot water. Opening hours are collected as data and give the weekly hours, but the
model does not use them (its occupancy profile is synthetic).

**Physics.** Hourly heat balance per basin (indoor: Delgado Marin and Garcia-Cascales, outdoor: Buscemi et al.) and sensible
hall demand. Weather is the PVGIS typical year of the zone T5 or T6 (default T6 if the postcode is not mapped). Stored heat is `C (T - T_min)` up to `C (T_max - T_min)`.

**Charging rule** (SPLASH `hysteresis_addon`). The resistive heater runs on curtailed power only. While the zone has
curtailed power it covers the hall and the basins first and then charges all basins to the upper limit. Outside curtailment
the basins cool towards the lower limit and the existing plant supplies the rest. The baseline holds the lower limit all year
with the existing plant.

**Heater size.** 100 %, 200 % and 300 % of the design load. The design load is the coincident peak (100th percentile) hold
load of all basins at their lower limit plus the hall, taken from the full year 2025 so that both years share one size.
Electric capacity = thermal capacity / 0.99. The design load includes the hot water peak.

**Curtailment data.** Hourly means of the 15 minute operator values (MW) of the zones T5 and T6 for 2025 (full year) and
2026 (to 22 November). `scripts/build_curtailment.py` converts local time with the CET/CEST label to UTC, so the autumn
repetition of one hour is handled. The operator marks 05.10.2026 as N.A.; it is set to 0 and flagged. Hours after
22 November are flagged not observed. 2026 results cover 1 January to 22 November and are not scaled to a year.

**KPIs.** Absorbed curtailed power, displaced conventional heat, fuel saved (displaced heat times fuel input per useful heat
of the questionnaire, capped at the reported heat), investment, NPV, break-even price, CO2.

**Checks.** Every run evaluates the SPLASH verification balances (basin, hall, electricity, capacity, bounds, no grid power,
no heat without curtailment). Tests require the residuals to be below 1e-3.

**Limits.** The weather is a typical year and not the weather of 2025 or 2026, so wind, heat demand and curtailment are not
coincident. Occupancy profiles and hall geometry of the SPLASH package are assumptions. A single pool is small against the
zone, so competing demand does not limit it. The hold-time answer (question 11) is not used by the model. The zone is not
cut by Hamburg (T6 is merged with Hamburg). The aggregated flexibility threshold of 100 kW is shown as a message.

Price of curtailed power: the user enters a net price in EUR/MWh. The default is 23 EUR/MWh (parameter
`curtailed_price_eur_per_mwh`), shown from the start. VAT is applied as for other electricity. The **break-even price** is the electricity price at which NPV = 0. It is exact because NPV is linear in the price.

## 6. Economics (`economics.py`)

```
NPV = -(I - S) + sum_{t=1..N} [ F0 (1+gf)^t - E0 (1+ge)^t - OM (1+i)^t ] / (1+w)^t
gf = (1+i)(1+real fuel change) - 1,   ge = (1+i)(1+real electricity change) - 1
```

I investment (today's prices), S grant, F0 fuel cost saved and E0 electricity cost in today's prices, OM yearly maintenance
(share of I, grows with inflation i), w nominal WACC, N evaluation period (default 20 years). Defaults: WACC 7 %
(5 to 9 %), inflation 2 % (ECB target; Destatis 2.2 % in 2025), real price change heat +2 %, electricity +1 %.
All of them are editable on the results page; an entered value keeps the distance to the pessimistic and optimistic value.
A nominal WACC of 7 % with 2 % inflation equals a real rate of 4.9 %. Also reported: nominal internal rate of return (IRR),
simple payback and discounted payback. Investment: heat pump 850 EUR/kW + fixed part, heater 120 EUR/kW + controls
(all illustrative, editable).

**Optional demand calibration.** By default the demand is the SPLASH physics, unscaled. In the "What if?" panel the operator can
switch on "Adapt the model to my consumption". The model demand of 2025 is then scaled by one factor to the reported useful
heat times the parameter `reported_heat_pool_share` (default 0.8, the rest is showers and other use). The factor scales basins and hall only; the hot water of section 2b is added from the visitors. Storage size per kelvin
and the temperature band are not scaled, so a smaller demand makes the storage relatively larger. The factor is limited to
0.15 to 2, shown on the results page and stored with the submission. The model can give more heat per m² of water than the UBA median (about 1.9 to 2.2 times in five test layouts).
The switch lets an operator with reliable meter data see how much that matters; the default stays with the model.

## 7. CO2

Fuel saving x emission factor (gas 0.182, oil 0.266 kg/kWh). Electricity at the German grid mix 0.353 kg/kWh (UBA 2024,
another version says 0.363), falling 4 % per year over the evaluation period. For flexible heating the result is shown twice:
curtailed power counted at zero, and at the grid mix.

## 8. Ranges and tornado (`scenarios.py`)

Three full runs with all uncertain parameters at pessimistic, central, optimistic. The tornado changes one parameter at a time.
Pessimistic and optimistic describe the parameter case. With a negative NPV a high discount rate can shrink the loss,
so a bar can look "wrong". The chart caption says so.

## 9. What is not modelled

Part-load COP curves, defrost, hourly electricity prices, grid fees, revenues from flexibility markets,
domestic hot water legionella constraints, a hot water tank as a second storage in the hourly operation (it only enters the design load), evaporation as a function of temperature, and the optimisation that the
SPLASH oemof model does. These are candidates for the next version.


## 10. Provenance and technology selection

Every input carries one of six classes (`splash_calc/provenance.py`): entered, estimated by the operator, calculated from
operator inputs, SPLASH default, benchmark-based, model-generated. The classes describe the origin; they do not change a
value. The legacy three-way map of `inputs.py` is mapped as: entered to entered (or estimated by operator when the operator marks
consumption as estimated), estimated to calculated, default to SPLASH default, or benchmark for consumption, prices and boiler
efficiency. The heater is the default technology. The heat pump follows the same rule logic (grid electricity holds T_min,
curtailed power charges to T_max). Both use the same SPLASH demand, baseline and economic assumptions. The thermal battery shows
the theoretical capacity (kWh/K times band), the modelled usable maximum (peak state of charge) and the mean free capacity in
the curtailment window as separate numbers. The buffer tank exploration uses 1.163 kWh per m³ and K (physical constant of
water) and is shown apart from the pool. The temperature above setpoint in the dispatch explorer is the state of charge divided
by the volume-weighted kWh/K and is a modelled mean. The financial exploration calls `economics()` with changed inputs; the
hourly simulation is not rerun.
