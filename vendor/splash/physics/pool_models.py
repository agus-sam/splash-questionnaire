from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import indoor_delgado as idg
from . import outdoor_buscemi as ob


@dataclass
class OutdoorPoolModel:
    forcing: ob.OutdoorForcing
    geometry: ob.OutdoorGeometry
    params: ob.OutdoorParams
    environment: str = "outdoor"

    def __post_init__(self) -> None:
        self._v_wi, self._beta = ob.wind_at_pool(self.forcing, self.params)
        self._alpha = ob.solar_absorptance(self.forcing, self.params)

    def _run(self, t_w, sl):
        sl = sl or slice(0, len(self.forcing))
        f = self.forcing.slice(sl.start, sl.stop)
        return ob.heat_balance(t_w, f, self.geometry, self.params, v_wi=self._v_wi[sl], alpha_w=self._alpha[sl])

    def components(self, t_w, t_air=None, sl: slice | None = None) -> dict[str, np.ndarray]:
        r = self._run(t_w, sl)
        return {k: r[k] / 1000.0 for k in ("eva", "conv", "rad", "re", "sun", "loss", "net")}

    def net_loss_kw_per_m2(self, t_w, t_air=None, sl: slice | None = None) -> np.ndarray:
        return self._run(t_w, sl)["net"] / 1000.0

    def evap_kg_s_per_m2(self, t_w, t_air=None, sl: slice | None = None) -> np.ndarray:
        return self._run(t_w, sl)["evap_kg_m2_s"]


@dataclass
class IndoorPoolModel:
    forcing: idg.IndoorForcing
    geometry: idg.IndoorGeometry
    params: idg.IndoorParams
    rh_pct: float
    t_rs: float
    t_g: float
    wall_mode: str
    wall_offset_k: float
    t_wall_fixed: float
    environment: str = "indoor"

    def _t_wall(self, t_air):
        if self.wall_mode == "follow_air_offset":
            return np.asarray(t_air, dtype=float) + self.wall_offset_k
        return self.t_wall_fixed

    def _run(self, t_w, t_air, sl):
        if t_air is None:
            raise ValueError("indoor pools need the hall air temperature")
        sl = sl or slice(0, len(self.forcing))
        f = self.forcing.slice(sl.start, sl.stop)
        t_air = np.broadcast_to(np.asarray(t_air, dtype=float), (len(f),))
        return idg.heat_balance(t_w, t_air, self.rh_pct, self._t_wall(t_air), self.t_rs, self.t_g, f, self.geometry, self.params)

    def components(self, t_w, t_air=None, sl: slice | None = None) -> dict[str, np.ndarray]:
        r = self._run(t_w, t_air, sl)
        return {k: r[k] for k in ("evap", "rad", "cond", "conv", "renov", "loss")}

    def net_loss_kw_per_m2(self, t_w, t_air=None, sl: slice | None = None) -> np.ndarray:
        return self._run(t_w, t_air, sl)["loss"]

    def evap_kg_s_per_m2(self, t_w, t_air=None, sl: slice | None = None) -> np.ndarray:
        return self._run(t_w, t_air, sl)["evap_kg_m2_s"]
