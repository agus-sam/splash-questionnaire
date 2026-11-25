# Changelog

## 1.5.1

* Hot water tank: questions on the presence and size of a tank (litres or m³). The stored heat sets a window of 1 to 12 hours over which the
  shower peak is averaged in the design load, which lowers the design load and the heater size. Hourly operation, demand and heat pump
  capacity are unchanged. The tank is taken as fully usable. Warnings for a size outside 50 L to 100 m³ or a missing size.

## 1.5.0

* Hot water for showers, proportional to the number of visitors: annual visitors, or weekday and weekend visitors times open days and
  operating weeks; 50 L of shower water per visitor (VDI 2089 Part 1, lower end), 40 °C, mains water by month.
* Hot water is part of the model demand, the design load and the heater size. Hall air and hot water form one load block in the hourly
  model; the rule-based heat pump serves hot water at a 60 °C supply temperature.
* New questions: annual visitors, how the shower water is heated (central, separate, none), shower water per visitor (refine step).
* New parameters: shower water per visitor, shower temperature, mean stay in the water.
* The optional adaptation to the reported consumption scales basins and hall only; hot water follows the visitors.
* Results page: hot water in the demand charts, a note on visitors, litres, energy and peak, design load with the hot water share.
  Exports: hot water demand in the results table, total and hot water demand in the hourly table.
* Provenance: visitors as a new tracked input (the data confidence score counts 12 inputs).
* SPLASH facility model v1.3 vendored (adds the hot water model, off by default).

## 1.4

* Provenance for every input in six classes, with badges and a provenance table.
* Technology selection: electric heater (sizes 100, 200 and 300 % of the design load), heat pump, or both. The heat pump follows the SPLASH
  rule logic: grid electricity holds the lower temperature limit, curtailed power charges the pool to the upper limit.
* Results in five sections and seven visualisations: thermal battery, Sankey diagram, technology comparison, annual calendar, hourly dispatch
  explorer, investment and break-even views, operational readiness.
* Live feedback in the questionnaire, saved resolved inputs, PDF report and CSV exports.
* Combined pools: indoor or outdoor location per basin and an opening window for the outdoor basins. The heat recovery of the hall follows the
  SPLASH archetype for every ventilation answer.

## 1.3 and earlier

* The SPLASH facility model is the single basis of the heat demand for baseline, heat pump and flexible heating.
* Hourly operator curtailment of 2025 and 2026 for the zones T5 and T6; flexible heating results per year and heater size.
* Season dates, open days and opening hours; optional adaptation of the model to the reported consumption.
* Editable economics: nominal WACC with calculator, inflation, real price changes, evaluation period, prices and investment costs, IRR, payback,
  break-even price and CO2.
* Storage in Google Sheets with retry and read-back, resume codes, admin area, personal links, German and English texts.
* Tests for calculation, questionnaire, storage and the end-to-end app flow; vendor hashes and version consistency are checked.
