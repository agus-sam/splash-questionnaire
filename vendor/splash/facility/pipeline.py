from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime

import numpy as np
import pandas as pd

from .. import __version__, viz
from ..config import OPT_SIZE, Settings
from ..data_loader import load_data
from ..preprocessing import curtailment_kw, make_timeline, report_months
from . import kpis, sizing, verification
from .econ import econ_inputs
from .model import build_facility_models, plant_capacity_kw, set_technology
from .results import FacResult
from .zone import BASE, run_zone_mode

log = logging.getLogger("splash")

OPT_MODE = "hysteresis_optimised"
FOCUS_ORDER = ("hysteresis_replace", "hysteresis_addon", OPT_MODE)


def resolve_facility(data, ref) -> int | None:
    if ref is None:
        return None
    fac = data.facilities
    if isinstance(ref, (int, np.integer)) or str(ref).strip().isdigit():
        return int(ref) if int(ref) in set(fac["facility_id"].astype(int)) else None
    name = str(ref).strip().lower()
    hit = fac[fac["name"].str.lower() == name]
    if hit.empty:
        hit = fac[fac["name"].str.lower().str.contains(name, regex=False)]
    return int(hit.iloc[0]["facility_id"]) if len(hit) else None


def load_package(s: Settings):
    data = load_data(s.data_root())
    synthetic = [k for k, v in data.synthetic_flags.items() if v]
    viz.set_context(synthetic=synthetic)
    if synthetic:
        log.warning("=" * 78)
        log.warning("SYNTHETIC INPUTS: %s. RESULTS ARE FOR METHOD DEVELOPMENT ONLY.", ", ".join(synthetic))
        log.warning("=" * 78)
    return data


def setup(settings_path, overrides=None, quick=False):
    ov = list(overrides or [])
    if quick:
        ov += ["run.time_window.start=2026-02-09", "run.time_window.end=2026-02-15"]
    s = Settings.from_yaml(settings_path, ov)
    logging.basicConfig(level=getattr(logging, s.run.log_level), format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", force=True)
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S") if s.run.run_id == "auto" else s.run.run_id
    out = s.output_root() / run_id
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(settings_path, out / "settings_used.yaml")
    (out / "settings_resolved.json").write_text(json.dumps(s.to_dict(), indent=2, default=str))
    return s, out, run_id


def run(settings_path, overrides=None, quick=False, data=None) -> dict:
    t_start = time.time()
    s, out, run_id = setup(settings_path, overrides, quick)
    fc = s.facility
    data = data if data is not None else load_package(s)
    tl = make_timeline(data, s.run.time_window.start, s.run.time_window.end)
    ref_id = resolve_facility(data, fc.reference_facility)
    if fc.reference_facility is not None and ref_id is None:
        log.warning("facility.reference_facility %r is not in the data package", fc.reference_facility)
    fids = fc.facilities
    if fids is not None and ref_id is not None and ref_id not in {int(f) for f in fids}:
        fids = [*fids, ref_id]
        log.info("reference facility %d added to the restricted facility list", ref_id)
    fms = build_facility_models(data, s, tl, fids)
    months = report_months(tl.index_local)
    zones = sorted({fm.zone for fm in fms.values()})
    avail = {z: curtailment_kw(data, z, tl, s.access_share(z, data.coordinator)) for z in zones}
    tabs = out / "tables"
    tabs.mkdir(exist_ok=True)
    try:
        econ = econ_inputs(data, s)
    except Exception as exc:
        log.warning("economics skipped: %s", exc)
        econ = None
    k_year = 8760.0 / tl.n
    primary = fc.sizing.primary_scenario
    modes = list(fc.zone_modes)
    std_modes = [m for m in modes if m != OPT_MODE]
    if OPT_MODE in modes and econ is None:
        raise RuntimeError("scenario hysteresis_optimised needs the economics inputs (plant and electricity prices), they could not be loaded")
    zfac = {z: [fm for fm in fms.values() if fm.zone == z] for z in zones}

    set_technology(fms, s, fc.technologies[0])
    base_res = {
        z: run_zone_mode(
            zfac[z],
            {fm.facility_id: 0.0 for fm in zfac[z]},
            avail[z],
            "baseline",
            depth=fc.charge_depth,
            priority=fc.plant.shortage_priority,
            hold_margin_k=fc.hold_margin_k,
        )
        for z in zones
    }
    results: dict[tuple, dict[int, FacResult]] = {(BASE, BASE, z, "baseline"): base_res[z] for z in zones}
    zone_frames: dict[tuple, pd.DataFrame] = {(BASE, BASE, z, "baseline"): kpis.zone_hourly(zfac[z], base_res[z], avail[z]) for z in zones}
    tech_rows, flex_rows, check_rows, month_rows, flag_rows, lin_rows, size_rows = [], [], [], [], [], [], []
    opt_sizes: dict[str, dict[int, sizing.SizeResult]] = {}
    for z in zones:
        for fm in zfac[z]:
            flex_rows.append(
                kpis.flex_row(fm, BASE, BASE, "baseline", base_res[z][fm.facility_id], base_res[z][fm.facility_id], avail[z], 0.0, econ, k_year)
            )
            check_rows.append(
                {
                    **verification.facility_checks(fm, base_res[z][fm.facility_id], 0.0, fc.charge_depth, "baseline", avail[z]),
                    "technology": BASE,
                    "plant_size": BASE,
                    "mode": "baseline",
                }
            )
    for tech in fc.technologies:
        set_technology(fms, s, tech)
        cases = []
        if std_modes:
            for scen in fc.sizing.scenarios:
                cases.append(
                    (
                        scen,
                        {f: plant_capacity_kw(fm, scen)[0] for f, fm in fms.items()},
                        {f: plant_capacity_kw(fm, scen)[1] for f, fm in fms.items()},
                        std_modes,
                    )
                )
        if OPT_MODE in modes:
            sz = sizing.size_plants(fms, base_res, avail, econ, s, k_year, tech)
            opt_sizes[tech] = sz
            cases.append(
                (OPT_SIZE, {f: sz[f].size_kw_th for f in fms}, {f: sz[f].size_kw_th / fm.design["cop_design"] for f, fm in fms.items()}, [OPT_MODE])
            )
        for scen, qr, er, smodes in cases:
            keep = scen == primary or scen == OPT_SIZE
            flag_case = (scen == primary and bool(std_modes)) or (scen == OPT_SIZE and not std_modes)
            for z in zones:
                zf = zfac[z]
                res = {}
                for mode in smodes:
                    res[mode] = run_zone_mode(
                        zf, qr, avail[z], mode, depth=fc.charge_depth, priority=fc.plant.shortage_priority, hold_margin_k=fc.hold_margin_k
                    )
                    zone_frames[(tech, scen, z, mode)] = kpis.zone_hourly(zf, res[mode], avail[z])
                    if keep:
                        results[(tech, scen, z, mode)] = res[mode]
                focus = next(m for m in FOCUS_ORDER if m in res)
                for fm in zf:
                    f = fm.facility_id
                    tech_rows.append(kpis.technical_row(fm, tech, scen, qr[f], er[f], tl.n))
                    for mode, rr in res.items():
                        check_rows.append(
                            {
                                **verification.facility_checks(fm, rr[f], qr[f], fc.charge_depth, mode, avail[z]),
                                "technology": tech,
                                "plant_size": scen,
                                "mode": mode,
                            }
                        )
                        flex_rows.append(kpis.flex_row(fm, tech, scen, mode, rr[f], base_res[z][f], avail[z], qr[f], econ, k_year))
                    if scen == OPT_SIZE:
                        opt_sizes[tech][f].absorbed_rule_mwh_e = float(res[OPT_MODE][f].curt_el.sum() * 1e-3)
                    if keep:
                        for mode, rr in res.items():
                            mt = kpis.monthly(fm, rr[f], months)
                            month_rows.append(mt.reset_index().assign(technology=tech, mode=mode))
                            if flag_case and mode == focus:
                                flag_rows.append({"facility_id": f, "facility_name": fm.name, "technology": tech, **kpis.month_flags(mt)})
                        if flag_case:
                            lin_rows.append(verification.linearisation_check(fm, res[focus][f]).assign(technology=tech))
        if tech in opt_sizes:
            size_rows.append(sizing.sizing_table(opt_sizes[tech]))
        log.info("technology %s done (%.0f s)", tech, time.time() - t_start)

    tech_t, flex = pd.DataFrame(tech_rows), pd.DataFrame(flex_rows)
    tech_t.round(4).to_csv(tabs / "facility_technical.csv", index=False)
    flex.round(4).to_csv(tabs / "facility_flexibility.csv", index=False)
    pd.concat(month_rows).round(4).to_csv(tabs / "facility_monthly.csv", index=False)
    pd.DataFrame(flag_rows).to_csv(tabs / "facility_month_flags.csv", index=False)
    chk = pd.DataFrame(check_rows)
    chk.to_csv(tabs / "verification_balances.csv", index=False)
    lin = pd.concat(lin_rows) if lin_rows else pd.DataFrame()
    lin.round(4).to_csv(tabs / "verification_linearisation.csv", index=False)
    size_t = pd.concat(size_rows, ignore_index=True) if size_rows else pd.DataFrame()
    if len(size_t):
        size_t.round(3).to_csv(tabs / "facility_sizing.csv", index=False)

    zone_rows, sh_rows, sh_hourly = [], [], {}
    combos = sorted({k[:2] + (k[3],) for k in zone_frames}, key=lambda c: (c[0] != BASE, c))
    for tech, scen, mode in combos:
        frames = {z: zone_frames[(tech, scen, z, mode)] for z in zones}
        tag = f"{mode}" if tech == BASE else f"{tech}__{mode}"
        for z, df in frames.items():
            ann = kpis.period_table(df, tl.index_local, "A").iloc[0]
            zone_rows.append({"technology": tech, "plant_size": scen, "zone": z, "mode": mode, **ann.to_dict(), **verification.zone_checks(df)})
            if scen in (primary, BASE, OPT_SIZE):
                df.to_csv(tabs / f"zone_hourly__{z}__{tag}.csv.gz", index_label="hour", compression="gzip")
                kpis.period_table(df, tl.index_local, "M").round(3).to_csv(tabs / f"zone_monthly__{z}__{tag}.csv")
                kpis.period_table(df, tl.index_local, "D").round(3).to_csv(tabs / f"zone_daily__{z}__{tag}.csv")
        sh = kpis.aggregate(frames)
        sh_hourly[(tech, scen, mode)] = sh
        ann = kpis.period_table(sh, tl.index_local, "A").iloc[0]
        sh_rows.append({"technology": tech, "plant_size": scen, "mode": mode, **ann.to_dict(), **verification.zone_checks(sh)})
        if scen in (primary, BASE, OPT_SIZE):
            sh.to_csv(tabs / f"sh_hourly__{tag}.csv.gz", index_label="hour", compression="gzip")
            kpis.period_table(sh, tl.index_local, "M").round(3).to_csv(tabs / f"sh_monthly__{tag}.csv")
            kpis.period_table(sh, tl.index_local, "D").round(3).to_csv(tabs / f"sh_daily__{tag}.csv")
    zt, st = pd.DataFrame(zone_rows), pd.DataFrame(sh_rows)
    cap = tech_t.groupby(["technology", "plant_size"]).agg(
        n_facilities=("facility_id", "nunique"),
        p2h_rated_kw_th=("p2h_rated_kw_th", "sum"),
        p2h_el_capacity_kw_e=("p2h_el_capacity_kw_e", "sum"),
        annual_demand_mwh_th=("annual_facility_heat_demand_mwh_th", "sum"),
        storage_mwh_th=("thermal_storage_capacity_mwh_th", "sum"),
    )
    zt.round(3).to_csv(tabs / "zone_summary.csv", index=False)
    st.round(3).to_csv(tabs / "sh_summary.csv", index=False)
    cap.round(3).to_csv(tabs / "sh_capacity.csv")
    if econ is not None:
        sheet = flex.groupby(["technology", "plant_size", "mode"])[
            ["cost_total_eur_a", "cost_baseline_eur_a", "net_benefit_eur_a", "co2_t_a", "co2_baseline_t_a", "invest_eur"]
        ].sum()
        sheet.round(1).to_csv(tabs / "sh_economics.csv")
    if len(zones) == 2:
        for key, sh in sh_hourly.items():
            t = sum(zone_frames[(key[0], key[1], z, key[2])]["absorbed_kw_e"] for z in zones)
            assert np.allclose(sh["absorbed_kw_e"], t), "SH absorption must equal the sum of the zones"
    (out / "run_info.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "splash_version": __version__,
                "n_facilities": len(fms),
                "hours": tl.n,
                "zones": zones,
                "primary_plant_size": primary,
                "plant_sizes": list(fc.sizing.scenarios),
                "technologies": list(fc.technologies),
                "scenarios": ["baseline", *modes],
                "reference_facility": ref_id,
                "plant_configuration": fc.plant.configuration,
                "indoor_evaporation": fc.indoor_evaporation,
                "synthetic_inputs": [k for k, v in data.synthetic_flags.items() if v],
                "runtime_s": round(time.time() - t_start, 1),
            },
            indent=2,
        )
    )
    data.provenance.to_csv(tabs / "input_provenance.csv", index=False)
    result = {
        "settings": s,
        "out": out,
        "data": data,
        "tl": tl,
        "fms": fms,
        "avail": avail,
        "results": results,
        "tech": tech_t,
        "flex": flex,
        "zone": zt,
        "sh": st,
        "sh_hourly": sh_hourly,
        "zone_frames": zone_frames,
        "checks": chk,
        "lin": lin,
        "months": months,
        "run_id": run_id,
        "econ": econ,
        "technologies": list(fc.technologies),
        "modes": modes,
        "primary": primary,
        "sizing": size_t,
        "reference_facility": ref_id,
        "opt_sizes": opt_sizes,
    }

    from . import storage

    st = storage.compute(result)
    result["storage"] = st
    st["summary"].round(4).to_csv(tabs / "sh_storage_potential.csv", index=False)
    st["facility"].round(4).to_csv(tabs / "facility_storage_potential.csv", index=False)
    st["balance"].round(3).to_csv(tabs / "sh_charging_heat_balance.csv", index=False)
    if s.output.figures:
        from . import figures

        result["figures"] = figures.make_all(result)
    log.info("run %s done in %.0f s", run_id, time.time() - t_start)
    return result
