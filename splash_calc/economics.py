"""Economics: NPV, payback, break-even electricity price and CO2.

Nominal cash flows, discounted with the nominal WACC w:

NPV = -(I - S) + sum_{t=1..N} [F0 (1+gf)^t - E0 (1+ge)^t - OM (1+i)^t] / (1+w)^t

with the nominal growth rates gf = (1+i)(1+real fuel change)-1 and
ge = (1+i)(1+real electricity change)-1. F0, E0: costs in today's prices,
OM: yearly operation and maintenance (grows with inflation i), I: investment
(today's prices), S: grant. Because the NPV is linear in the
electricity price, the break-even price is exact.
"""
from __future__ import annotations

from dataclasses import dataclass

from .baseline import EF_NAME
from .params import Params


def pv_factor(growth: float, rate: float, years: int) -> float:
    """sum_{t=1..N} ((1+g)/(1+r))^t."""
    q = (1.0 + growth) / (1.0 + rate)
    if abs(q - 1.0) < 1e-12:
        return float(years)
    return float(q * (1.0 - q**years) / (1.0 - q))


@dataclass
class Economics:
    investment_eur: float
    subsidy_eur: float
    net_investment_eur: float
    fuel_saving_eur_y1: float
    electricity_cost_eur_y1: float
    om_eur_y: float
    net_saving_eur_y1: float
    npv_eur: float
    irr: float | None                  # nominal internal rate of return
    discounted_payback_years: float | None
    payback_years: float | None
    break_even_price: float | None     # EUR/kWh of electricity at which NPV = 0
    cumulative_cashflow: list[float]   # year 0..N (undiscounted)


def economics(
    investment_eur: float,
    subsidy_eur: float,
    fuel_saved_kwh: dict[str, float],
    fuel_prices: dict[str, float],
    elec_kwh: float,
    elec_price: float,
    om_eur_y: float,
    params: Params,
) -> Economics:
    n = int(params.get("lifetime_years"))
    w = float(params.get("wacc"))
    infl = float(params.get("inflation"))
    gf = (1 + infl) * (1 + float(params.get("price_escalation_fuel"))) - 1
    ge = (1 + infl) * (1 + float(params.get("price_escalation_electricity"))) - 1
    r = w

    f0 = sum(fuel_saved_kwh[c] * fuel_prices[c] for c in fuel_saved_kwh)
    e0 = elec_kwh * elec_price
    net_inv = investment_eur - subsidy_eur

    pvf, pve, pv0 = pv_factor(gf, r, n), pv_factor(ge, r, n), pv_factor(infl, r, n)
    npv = -net_inv + f0 * pvf - e0 * pve - om_eur_y * pv0

    a_term = -net_inv + f0 * pvf - om_eur_y * pv0
    b_term = elec_kwh * pve
    break_even = a_term / b_term if b_term > 0 else None

    y1 = f0 * (1 + gf) - e0 * (1 + ge) - om_eur_y * (1 + infl)
    payback = net_inv / y1 if y1 > 0 and net_inv > 0 else (0.0 if net_inv <= 0 and y1 > 0 else None)
    if payback is not None and payback > n:
        payback = None

    flows = [f0 * (1 + gf) ** t - e0 * (1 + ge) ** t - om_eur_y * (1 + infl) ** t for t in range(1, n + 1)]
    cum = [-net_inv]
    for cf in flows:
        cum.append(cum[-1] + cf)
    disc, acc = None, -net_inv
    for t, cf in enumerate(flows, start=1):
        prev = acc
        acc += cf / (1 + r) ** t
        if disc is None and acc >= 0 > prev:
            disc = float(t - 1 + (-prev) / (acc - prev))
    if net_inv <= 0 and flows and flows[0] > 0:
        disc = 0.0
    irr = _irr([-net_inv] + flows)

    return Economics(
        investment_eur=investment_eur,
        subsidy_eur=subsidy_eur,
        net_investment_eur=net_inv,
        fuel_saving_eur_y1=f0,
        electricity_cost_eur_y1=e0,
        om_eur_y=om_eur_y,
        net_saving_eur_y1=y1,
        npv_eur=float(npv),
        irr=irr,
        discounted_payback_years=disc,
        payback_years=payback,
        break_even_price=break_even,
        cumulative_cashflow=[float(x) for x in cum],
    )


def _irr(cash: list[float]) -> float | None:
    """Internal rate of return by bisection. None if there is no sign change."""
    if not (any(c < 0 for c in cash) and any(c > 0 for c in cash)):
        return None

    def f(rate: float) -> float:
        return sum(c / (1 + rate) ** i for i, c in enumerate(cash))

    lo, hi = -0.5, 1.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return float(0.5 * (lo + hi))


# ------------------------------------------------------------------------ CO2
@dataclass
class Co2:
    saved_fuel_t_y1: float
    elec_grid_t_y1: float
    net_t_y1: float                    # electricity at grid mix
    net_curtailed_zero_t_y1: float     # curtailed electricity counted at zero
    lifetime_net_t: float
    lifetime_net_curtailed_zero_t: float


def co2(
    fuel_saved_kwh: dict[str, float],
    elec_kwh: float,
    params: Params,
    curtailed_share: float = 0.0,
) -> Co2:
    """CO2 balance in tonnes. ``curtailed_share`` is the share of the electricity
    that comes from curtailed renewables (1.0 for the flexible heating scenario).
    That share is counted at ``ef_curtailed`` in the second view."""
    n = int(params.get("lifetime_years"))
    ef0 = float(params.get("ef_electricity"))
    dec = float(params.get("ef_electricity_decline_per_year"))
    ef_c = float(params.get("ef_curtailed"))

    fuel_kg = sum(v * float(params.get(EF_NAME[c])) for c, v in fuel_saved_kwh.items())

    def el_kg(t: int, share_curt: float) -> float:
        ef_t = ef0 * (1.0 - dec) ** t
        return elec_kwh * ((1.0 - share_curt) * ef_t + share_curt * ef_c)

    life_grid = sum(fuel_kg - el_kg(t, 0.0) for t in range(1, n + 1))
    life_curt = sum(fuel_kg - el_kg(t, curtailed_share) for t in range(1, n + 1))
    return Co2(
        saved_fuel_t_y1=fuel_kg / 1000.0,
        elec_grid_t_y1=el_kg(1, 0.0) / 1000.0,
        net_t_y1=(fuel_kg - el_kg(1, 0.0)) / 1000.0,
        net_curtailed_zero_t_y1=(fuel_kg - el_kg(1, curtailed_share)) / 1000.0,
        lifetime_net_t=life_grid / 1000.0,
        lifetime_net_curtailed_zero_t=life_curt / 1000.0,
    )


def investment_hp(capacity_kw_th: float, params: Params) -> tuple[float, float]:
    """Return (investment, yearly O&M) of the heat pump."""
    inv = capacity_kw_th * float(params.get("hp_capex_per_kw_th")) + float(params.get("hp_capex_fixed"))
    return inv, inv * float(params.get("hp_om_rate"))


def investment_flex(variant: str, capacity_kw_th: float, capacity_kw_el: float, params: Params) -> tuple[float, float]:
    """Investment and O&M of the flexibility device (heater or heat pump plus controls)."""
    fixed = float(params.get("flex_capex_fixed"))
    if variant == "heater":
        inv = capacity_kw_el * float(params.get("heater_capex_per_kw_el")) + fixed
    else:
        inv = capacity_kw_th * float(params.get("hp_capex_per_kw_th")) + float(params.get("hp_capex_fixed")) + fixed
    return inv, inv * float(params.get("flex_om_rate"))

