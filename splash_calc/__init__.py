"""SPLASH Questionnaire and Simulation calculation core (no Streamlit imports)."""
from .inputs import PoolInputs, from_answers
from .params import Params
from .scenarios import Options, Result, run

__all__ = ["Params", "PoolInputs", "Options", "Result", "from_answers", "run"]
__version__ = "1.5.1"
