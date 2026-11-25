import pandas as pd

from splash_calc import climate


def test_zone_mapping_longest_prefix(tmp_path):
    pd.DataFrame({"plz_prefix": ["2", "24", "249"], "zone": ["A", "B", "C"]}).to_csv(tmp_path / "zones.csv", index=False)
    assert climate.zone_for_postcode("24937", tmp_path) == ("C", True)
    assert climate.zone_for_postcode("24100", tmp_path) == ("B", True)
    assert climate.zone_for_postcode("99999", tmp_path) == (climate.DEFAULT_ZONE, False)
    assert climate.zone_for_postcode("", tmp_path) == (climate.DEFAULT_ZONE, False)
