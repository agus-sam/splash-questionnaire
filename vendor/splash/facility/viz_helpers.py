from __future__ import annotations


def pick_samples(R) -> list[int]:
    fms = R["fms"]
    want = R["settings"].facility.sample_facilities
    ref = R.get("reference_facility")
    out = [ref] if ref in fms else []
    if want:
        out += [int(f) for f in want if int(f) in fms]
    else:
        for typ in ("Hallenbad", "Freibad", "Kombibad"):
            c = [f for f in fms.values() if f.model_type == typ]
            if c:
                out.append(max(c, key=lambda f: (f.n_basins, f.facility_id)).facility_id)

        for z in sorted({f.zone for f in fms.values()} - {fms[i].zone for i in out}):
            out.append(max((f for f in fms.values() if f.zone == z), key=lambda f: (f.total_demand_kw().sum(), f.facility_id)).facility_id)
    return list(dict.fromkeys(out))
