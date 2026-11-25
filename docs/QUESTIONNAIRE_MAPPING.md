# Questionnaire mapping

Generated from `data/questions.yaml` (version 1.5.1). Do not edit by hand, run `python scripts/make_mapping.py`.

`draft` = from your questionnaire draft v1, `added` = added for the calculation or the research design. `feeds` says whether the answer drives the calculation, the research evaluation, or the contact table.

## Step 0: Welcome

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q0_consent` | checkbox | added | research | yes | I have read the privacy notice and take part voluntarily. |

## Step 1: Your pool

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q1_name` | text | draft | research | yes | 1. Name of the pool |
| `q1_city` | text | draft | research | yes | City / region |
| `q1_postcode` | text | added | calculation | yes | Postal code |
| `q1_role` | single | draft | research | yes | Your role |
| `q1_role_other` | text | draft | research |  | Other role |
| `q1_pool_type` | single | added | calculation | yes | Type of pool |
| `q1_legal_form` | single | added | calculation | yes | Operator type |
| `q2_year_built` | number | draft | research |  | 2. Year built |
| `q2_year_renov` | number | draft | research |  | Year of last major renovation (leave empty if none) |
| `q3_basins` | basins | draft | calculation | yes | 3. Which basins does your pool have? |
| `q3_hall_area` | number | added | calculation |  | Hall floor area (m²) |
| `q3_auto_temp` | single | draft | research |  | Is temperature regulated automatically? |
| `q4_season` | season | added | calculation |  | When is the pool open? (season) |
| `q4_season_outdoor` | season | added | calculation |  | When are the outdoor basins open? |
| `q4_days` | weekdays | added | research |  | On which days is the pool open? |
| `q4_hours` | hours | added | research |  | Opening hours |
| `q4_visitors_weekday` | number | draft | calculation |  | 4. Typical visitors on weekdays (people per day) |
| `q4_visitors_weekend` | number | draft | calculation |  | Typical visitors on weekends (people per day) |
| `q4_visitors_year` | number | added | calculation |  | Visitors per year (if known) |
| `q4_dhw_supply` | single | added | calculation |  | How is the shower water heated? |
| `q4_dhw_tank` | single | added | calculation |  | Is there a hot water tank for the showers? |
| `q4_dhw_tank_size` | number | added | calculation |  | Size of the hot water tank |
| `q4_dhw_tank_unit` | single | added | calculation |  | Unit of the tank size |
| `q4_peaks` | textarea | draft | research |  | Busiest periods and hours (e.g. weekday evenings, school swimming mornings) |
| `q5_temp_change` | single | draft | research |  | 5. Have you ever raised or lowered pool temperatures (e.g. during the energy crisis)? |
| `q5_effects` | textarea | draft | research |  | What were the effects (energy savings, visitor complaints, hygiene, technical issues)? |
| `q6_air_setpoint` | number | draft | calculation |  | 6. Hall air temperature setpoint (°C) |
| `q6_humidity` | single | draft | research |  | Humidity control |
| `q6_ventilation` | single | draft | calculation |  | Ventilation |

## Step 2: Energy

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q7_sources` | multi | draft | calculation | yes | 7. Which heat sources do you use? |
| `q7_main_source` | single | draft | calculation | yes | Main source |
| `q7_main_capacity_kw` | number | draft | research |  | Approximate capacity of the main source (kW) |
| `q8_consumption` | consumption | draft | calculation |  | 8. Annual energy consumption (last 1 to 3 years) |
| `q8_later` | checkbox | draft | research |  | I will check and send this later. |
| `q8_quality` | single | added | calculation |  | How reliable are these consumption figures? |
| `q8_heat_cost_eur` | number | added | calculation |  | Annual heat cost (EUR, optional) |
| `q8_elec_cost_eur` | number | added | calculation |  | Annual electricity cost (EUR, optional) |
| `q8_costs_incl_vat` | single | added | calculation |  | Are the costs gross or net? |

## Step 3: Flexibility

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q9_programme` | single | draft | research |  | 9. Are you already in a flexibility programme? |
| `q9b_equipment` | multi | draft | research |  | 9b. Do you have, or plan, any of the following? |
| `q9b_status` | single | draft | research |  | Status |
| `q9b_buffer_m3` | number | added | research |  | Buffer tank volume (m³, optional) |
| `q9b_pv_kwp` | number | added | research |  | PV capacity (kWp, optional) |
| `q10_willing` | scale | draft | research | yes | 10. How willing would you be to heat your pool more flexibly with electricity when prices are low or renewable electricity is abundant? |
| `q11_change` | single | draft | calculation | yes | 11. By how much could the pool water temperature rise above the setpoint? |
| `q11_hold` | single | draft | research |  | For how long at a time? |
| `q12_needs` | multi | draft | research |  | 12. What would you need in return? |
| `q12_barriers` | multi | draft | research |  | Main barriers |
| `q12_other` | text | draft | research |  | Other (need or barrier) |
| `q12b_model` | single | added | research |  | Which model would be most attractive to you? |
| `q12c_decision` | single | added | research |  | Who decides on investments in the heat supply? |
| `q13_interest` | single | draft | research |  | 13. Interest in renewable energy for pool heating |
| `q13_which` | multi | draft | research |  | Which? |

## Step 4: Your results

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q10_post` | scale | added | research |  | After seeing your results: how willing would you be now to heat your pool more flexibly? |
| `q10_post_useful` | scale | added | research |  | How useful are these results to you? |
| `q10_post_comment` | textarea | added | research |  | What looks wrong or is missing from your view? (optional) |

## Step 5: Refine

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `r_shower_litres` | number | added | calculation |  | Shower water per visitor (litres, if known) |
| `r_boiler_age` | number | added | calculation |  | Age of the main boiler (years) |
| `r_boiler_eta` | number | added | calculation |  | Boiler efficiency (%, if known) |
| `r_grid_kw` | number | added | calculation |  | Electrical connection capacity (kW) |
| `r_dh_contract` | single | added | calculation |  | Does a district heating contract bind you (connection and take-or-pay)? |
| `r_hp_source` | single | added | calculation |  | Heat source for a heat pump |

## Step 6: Follow-up

| id | type | origin | feeds | required | question (EN) |
|---|---|---|---|---|---|
| `q14_interview` | single | draft | research | yes | 14. Would you join for a follow-up interview? |
| `q14_comments` | textarea | draft | research |  | Any other comments |
| `q14_contact_name` | text | draft | contact |  | Name (optional) |
| `q14_contact_email` | text | draft | contact |  | Email or phone (optional) |
| `q14_contact_method` | single | draft | contact |  | Preferred contact method |
| `q14_consent` | checkbox | draft | contact |  | I agree that my contact details may be stored and used to contact me about this project (data protection consent). |
| `q14_summary` | checkbox | added | contact |  | I would like to receive the summary of the findings. |

Total: 70 items, 38 from the draft, 32 added.
