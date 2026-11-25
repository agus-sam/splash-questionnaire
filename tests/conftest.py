import copy
import os
import tempfile

import pytest

# Keep tests away from the repository: local SQLite goes to a temp folder.
_TMP = tempfile.mkdtemp(prefix="splash-tests-")
os.environ.setdefault("SPLASH_SQLITE_PATH", os.path.join(_TMP, "test.db"))

from splash_app.demo import DEMO_ANSWERS  # noqa: E402
from splash_calc import Params  # noqa: E402


@pytest.fixture
def answers():
    return copy.deepcopy(DEMO_ANSWERS)


@pytest.fixture
def params():
    return Params.load()
