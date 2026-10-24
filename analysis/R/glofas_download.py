#!/usr/bin/env python3
"""
glofas_download.py  —  download GloFAS v4 daily river discharge (2003-2022) covering all 12 cities.

Run from the LeapTo folder:
    python3 R/glofas_download.py test     # one day for the whole box (checks the request is accepted): ~1-2 minutes
    python3 R/glofas_download.py          # everything: one box per year = 20 requests

One box covers all 12 cities (each city's barangays plus ~15 km), one request per year, because nearly all
the time is spent waiting in the Copernicus queue, not downloading. If Copernicus refuses a request as too
large, that year is split automatically into three regional boxes (Luzon, Visayas, Mindanao).
The city areas are cut out afterwards; the values are the same grid cells as smaller boxes would give.

Needs: ~/.cdsapirc (EWDS url + personal access token), the GloFAS licence accepted on the dataset page,
       pip3 install "cdsapi>=0.7.7" xarray netCDF4
Output: data/external/glofas/all/glofas_all_<year>.nc  (about 20 MB per year)
        or data/external/glofas/<region>/glofas_<region>_<year>.nc after a split
Safe to stop and re-run: finished years are skipped.
Earlier per-city files (data/external/glofas/dagupan/ ...) are kept and used to check the new files match.
"""
import os, sys, time, json, zipfile, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import cdsapi
except ImportError:
    sys.exit('cdsapi is not installed. Run:  pip3 install "cdsapi>=0.7.7" xarray netCDF4')

DATASET = "cems-glofas-historical"
YEARS = range(2003, 2023)
OUT = os.path.join("data", "external", "glofas")
WORKERS = 4
RETRIES = 3

# [North, West, South, East]
ALL_BOX = [16.30, 120.15, 6.70, 125.85]            # every city's area below
REGIONS = {                                         # fallback if ALL_BOX is refused as too large
    "luzon":    [16.30, 120.15, 12.80, 124.05],     # Dagupan, Palayan, Metro Manila, Legazpi
    "visayas":  [11.55, 122.30, 10.10, 125.25],     # Iloilo, Mandaue, Tacloban
    "mindanao": [ 8.70, 121.70,  6.70, 125.85],     # Zamboanga, Cagayan de Oro, Davao
}

# Copernicus has renamed request fields over time. The earlier test saved the variant that works
# (data/external/glofas/request_style.json); if it is missing, the test tries these in order.
STYLES = [
    {"date_keys": ["year", "month", "day"], "timespan": None},
    {"date_keys": ["hyear", "hmonth", "hday"], "timespan": None},
    {"date_keys": ["year", "month", "day"], "timespan": "time_mean"},
    {"date_keys": ["hyear", "hmonth", "hday"], "timespan": "time_mean"},
]
STYLE_FILE = os.path.join(OUT, "request_style.json")
STYLE = STYLES[0]
TOO_LARGE = ("too large", "cost", "exceed", "size limit", "request is too")
QUEUE_FULL = "maximum number queued"          # Copernicus queue limit: wait and try again, not an error
WAIT_QUEUE = 60


def retrieve_waiting(client, req, target):
    """fetch(), but if the Copernicus queue limit is reached, wait and try again (as long as it takes)."""
    waited = 0
    while True:
        try:
            return fetch(client, req, target)
        except Exception as e:
            if QUEUE_FULL in str(e).lower():
                if waited % 600 == 0:
                    print(f"  ({time.strftime('%H:%M:%S')}) Copernicus queue is full; waiting and retrying every {WAIT_QUEUE}s ...", flush=True)
                time.sleep(WAIT_QUEUE); waited += WAIT_QUEUE
                continue
            raise


def request(area, year, months=None, days=None, style=None):
    st = style or STYLE
    ky, km, kd = st["date_keys"]
    r = {
        "system_version": ["version_4_0"],
        "hydrological_model": ["lisflood"],
        "product_type": ["consolidated"],
        "variable": ["average_river_discharge_in_the_last_24_hours"],
        ky: [str(year)],
        km: months or [f"{m:02d}" for m in range(1, 13)],
        kd: days or [f"{d:02d}" for d in range(1, 32)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": area,
    }
    if st["timespan"]:
        r["timespan"] = [st["timespan"]]
    return r


def fetch(client, req, target):
    """Download to a temporary file, unzip if Copernicus sent a zip, then move into place."""
    tmp = target + ".part"
    client.retrieve(DATASET, req, tmp)
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            nc = [n for n in z.namelist() if n.endswith(".nc")]
            if not nc:
                raise RuntimeError("zip from Copernicus has no .nc file: " + ", ".join(z.namelist()))
            with z.open(nc[0]) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.remove(tmp)
    else:
        os.replace(tmp, target)


def check(path):
    """Return (number of days, max discharge) for a downloaded file."""
    try:
        import xarray as xr
        with xr.open_dataset(path) as ds:
            var = [v for v in ds.data_vars if ds[v].ndim >= 3][0]
            tdim = [d for d in ds[var].dims if "time" in d.lower()][0]
            return ds.sizes[tdim], float(ds[var].max())
    except ImportError:
        from netCDF4 import Dataset
        with Dataset(path) as ds:
            var = [v for v in ds.variables if ds.variables[v].ndim >= 3][0]
            return ds.variables[var].shape[0], float(ds.variables[var][:].max())


def get_one(client, name, area, year):
    """One file with retries. Returns a status string; 'TOO_LARGE' if Copernicus refuses the size."""
    target = os.path.join(OUT, name, f"glofas_{name}_{year}.nc")
    if os.path.exists(target):
        return "already there"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    expected = 366 if year % 4 == 0 else 365
    for attempt in range(1, RETRIES + 1):
        try:
            t0 = time.time()
            retrieve_waiting(client, request(area, year), target)
            n, mx = check(target)
            if n != expected:
                os.remove(target)
                raise RuntimeError(f"got {n} days, expected {expected}")
            mb = os.path.getsize(target) / 1e6
            return f"ok ({n} days, {mb:.1f} MB, {time.time() - t0:.0f}s)"
        except Exception as e:
            msg = str(e)
            if any(w in msg.lower() for w in TOO_LARGE) and "days" not in msg and QUEUE_FULL not in msg.lower():
                return "TOO_LARGE"
            if attempt == RETRIES:
                return "FAILED: " + msg.strip().splitlines()[-1][:200]
            time.sleep(20 * attempt)


def get_year(client, year):
    """The whole box for one year; if it is refused as too large, the three regional boxes instead."""
    s = get_one(client, "all", ALL_BOX, year)
    if s != "TOO_LARGE":
        return year, s
    parts = [f"{r}: {get_one(client, r, box, year)}" for r, box in REGIONS.items()]
    return year, "split into regions -> " + "; ".join(parts)


def main():
    global STYLE
    client = cdsapi.Client(quiet=True, progress=False)
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(STYLE_FILE):
        with open(STYLE_FILE) as f:
            STYLE = json.load(f)
        styles = [STYLE]
    else:
        styles = STYLES

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        target = os.path.join(OUT, "test_all_2011-12-17.nc")
        print("Requesting one day (17 Dec 2011) for the whole box covering all 12 cities ... (waits in the Copernicus queue)")
        for box_name, box in [("whole box", ALL_BOX)] + [(f"{r} region", b) for r, b in REGIONS.items()]:
            for i, st in enumerate(styles, 1):
                t0 = time.time()
                try:
                    retrieve_waiting(client, request(box, 2011, ["12"], ["17"], style=st), target)
                except Exception as e:
                    print(f"  {box_name}, variant {i}: not accepted: {str(e).strip().splitlines()[-1][:250]}")
                    continue
                n, mx = check(target)
                with open(STYLE_FILE, "w") as f:
                    json.dump(st, f)
                print(f"\nTEST OK ({box_name}): {n} day(s), {os.path.getsize(target) / 1e3:.0f} KB for one day, "
                      f"highest discharge {mx:.0f} m3/s, {time.time() - t0:.0f}s")
                if box_name != "whole box":
                    print("The whole box was refused, so the full download will use the three regional boxes.")
                print("Now run:  python3 R/glofas_download.py")
                return
        sys.exit("\nNo request was accepted. Paste this whole output to Claude.")

    print(f"{len(YEARS)} requests (one box per year covering all 12 cities), {WORKERS} at a time. Safe to stop and re-run.")
    done, failed = 0, []
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = [pool.submit(get_year, client, y) for y in YEARS]
        for f in as_completed(futs):
            year, status = f.result()
            done += 1
            print(f"[{done:2d}/{len(YEARS)}] {time.strftime('%H:%M:%S')} {year}: {status}", flush=True)
            if "FAILED" in status:
                failed.append(year)
    if failed:
        print(f"\n{len(failed)} years had a failed request ({', '.join(map(str, sorted(failed)))}). "
              "Re-run the same command to retry them.")
    else:
        print(f"\nALL DONE: {len(YEARS)} years in {OUT}")


if __name__ == "__main__":
    main()
