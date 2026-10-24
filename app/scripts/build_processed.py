"""Build every file in data/processed/ from the raw Project CCHAIN CSVs.

Run once (about 1-2 minutes, dominated by the 6.4M-row climate file):

    python scripts/build_processed.py

The Streamlit app never reads data/raw/; it reads only what this writes:
    cities.parquet        one row per city: names, province, region, centroid
    cities.geojson        dissolved + simplified city polygons for the map
    cases_weekly.parquet  lepto cases per city x aligned DOH morbidity week
    rain_daily.parquet    barangay-mean rainfall per city per day (2003-2022)
    rain_weekly.parquet   the same summed to morbidity weeks
    pop_yearly.parquet    population per city per year (2020 carried forward)
    hazard_city.parquet   area-weighted Project NOAH hazard shares per city
    brgy_flood_rank.csv   barangays ranked by 100-yr high flood-hazard share

Only the barangay ranking (seconds, needs location.csv + project_noah_hazards.csv):

    python scripts/build_processed.py --only-flood-rank
"""

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]      # the app folder
for _p in (ROOT, ROOT.parent):                  # src/ and the `app` package
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import config  # noqa: E402
from src.aggregate import (barangay_flood_rank, brgy_to_city, city_hazard,  # noqa: E402
                           city_population, combine_rain_partials, daily_to_weekly_rain,
                           rain_partial_sums, weekly_lepto_cases)

# CONFIG +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

CLIMATE_CHUNK_ROWS = 1_000_000
# ~0.0005 deg is ~55 m: keeps coastlines recognisable, cuts the file ~10x.
SIMPLIFY_TOLERANCE_DEG = 0.0005


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def log(msg, t0):
    """Print a progress line with seconds elapsed since `t0`.

    Parameters
    ----------
    msg : str
        Message to print.
    t0 : float
        time.perf_counter() value at script start.

    Returns
    -------
    None
    """
    print(f"[{time.perf_counter() - t0:6.1f}s] {msg}", flush=True)


# GEOGRAPHY ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def build_cities(lookup, geography_csv):
    """Dissolve barangay polygons into city polygons and a city table.

    Parameters
    ----------
    lookup : pandas.DataFrame
        Output of src.aggregate.brgy_to_city.
    geography_csv : pathlib.Path
        brgy_geography.csv with a WKT `geometry` column in lon/lat (EPSG:4326).

    Returns
    -------
    tuple[geopandas.GeoDataFrame, pandas.DataFrame]
        (city polygons with adm3_pcode/city_name/province/region,
         city table adding lat/lon of a point guaranteed inside the polygon,
         n_brgy and area_km2). Raises ValueError if any barangay lacks a shape.
    """
    geo = pd.read_csv(geography_csv, usecols=["adm4_pcode", "geometry"])
    missing = set(lookup.adm4_pcode) - set(geo.adm4_pcode)
    if missing:
        raise ValueError(f"{len(missing)} barangays have no polygon, e.g. {sorted(missing)[:3]}")
    gdf = gpd.GeoDataFrame(geo[["adm4_pcode"]],
                           geometry=gpd.GeoSeries.from_wkt(geo.geometry, crs="EPSG:4326"))
    gdf = gdf.merge(lookup, on="adm4_pcode", how="inner")

    city_cols = ["adm3_pcode", "city_name", "province", "region"]
    cities = gdf.dissolve(by=city_cols, as_index=False,
                          aggfunc={"adm4_pcode": "count", "brgy_area_km2": "sum"})
    cities = cities.rename(columns={"adm4_pcode": "n_brgy", "brgy_area_km2": "area_km2"})
    cities["geometry"] = cities.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)

    inside = cities.geometry.representative_point()
    table = pd.DataFrame(cities.drop(columns="geometry"))
    table["lat"], table["lon"] = inside.y.values, inside.x.values
    return cities[[*city_cols, "geometry"]], table


def write_flood_rank(noah, lookup, t0):
    """Write data/processed/brgy_flood_rank.csv.

    Parameters
    ----------
    noah : pandas.DataFrame
        Raw project_noah_hazards.csv.
    lookup : pandas.DataFrame
        brgy_to_city output.
    t0 : float
        Start time for the log line.

    Returns
    -------
    None. Writes a small CSV (committed) so the app needs no raw files.
    """
    rank = barangay_flood_rank(noah, lookup, column=config.FLOOD_HAZARD_COLUMN)
    rank.to_csv(PROCESSED / config.FLOOD_RANK_FILE, index=False)
    log(f"barangay flood rank: {len(rank)} barangays in {rank.adm3_pcode.nunique()} cities", t0)


# MAIN +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def main(argv=None):
    """Run the full raw -> processed pipeline and write every output file.

    Parameters
    ----------
    argv : list[str] | None
        CLI arguments; `--skip-climate` reuses existing rain parquet files
        (handy when iterating on the small datasets); `--only-flood-rank`
        writes brgy_flood_rank.csv and nothing else.

    Reads
    -----
    All CSVs in data/raw/. climate_atmosphere.csv is streamed in chunks of
    CLIMATE_CHUNK_ROWS with only adm4_pcode, date and pr loaded.

    Returns
    -------
    None. Writes to data/processed/ and prints a short validation summary.
    Raises on any structural problem (missing shapes, duplicate weeks).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-climate", action="store_true")
    parser.add_argument("--only-flood-rank", action="store_true")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    lookup = brgy_to_city(pd.read_csv(RAW / "location.csv"))
    noah = pd.read_csv(RAW / "project_noah_hazards.csv")
    write_flood_rank(noah, lookup, t0)
    if args.only_flood_rank:
        return

    # Cities and polygons
    polygons, cities = build_cities(lookup, RAW / "brgy_geography.csv")
    polygons.to_file(PROCESSED / "cities.geojson", driver="GeoJSON")
    cities.to_parquet(PROCESSED / "cities.parquet", index=False)
    log(f"cities: {len(cities)} cities, geojson "
        f"{(PROCESSED / 'cities.geojson').stat().st_size / 1e6:.1f} MB", t0)

    # Cases
    pidsr = pd.read_csv(RAW / "disease_pidsr_totals.csv",
                        usecols=["date", "adm3_pcode", "disease_common_name", "case_total"])
    cases = weekly_lepto_cases(pidsr, cities)
    cases.to_parquet(PROCESSED / "cases_weekly.parquet", index=False)
    na_weeks = cases[cases.cases.isna()].drop_duplicates("week_start")
    log(f"cases: {len(cases):,} rows, {cases.week_start.min().date()} -> "
        f"{cases.week_start.max().date()}, NA weeks: "
        f"{[f'{r.mw_year}-W{r.mw_week}' for r in na_weeks.itertuples()]}", t0)

    # Population and hazard
    pop = city_population(pd.read_csv(RAW / "worldpop_population.csv"), lookup)
    pop.to_parquet(PROCESSED / "pop_yearly.parquet", index=False)
    hazard = city_hazard(noah, lookup)
    hazard.to_parquet(PROCESSED / "hazard_city.parquet", index=False)
    log(f"population: {pop.year.min()}-{pop.year.max()}; hazard: {len(hazard)} cities", t0)

    # Rainfall (the heavy one)
    if args.skip_climate:
        log("rain: skipped (--skip-climate)", t0)
    else:
        partials = []
        reader = pd.read_csv(RAW / "climate_atmosphere.csv",
                             usecols=["adm4_pcode", "date", "pr"],
                             dtype={"adm4_pcode": "category"},
                             chunksize=CLIMATE_CHUNK_ROWS)
        for i, chunk in enumerate(reader, 1):
            chunk["adm4_pcode"] = chunk.adm4_pcode.astype(str)
            partials.append(rain_partial_sums(chunk, lookup))
            log(f"rain: chunk {i} read", t0)
        daily = combine_rain_partials(partials)
        weekly = daily_to_weekly_rain(daily)
        daily.to_parquet(PROCESSED / "rain_daily.parquet", index=False)
        weekly.to_parquet(PROCESSED / "rain_weekly.parquet", index=False)
        log(f"rain: {len(daily):,} city-days, {len(weekly):,} city-weeks, "
            f"{daily.date.min().date()} -> {daily.date.max().date()}", t0)

    log("done", t0)


if __name__ == "__main__":
    main()
