#!/usr/bin/env python3
"""
07d_glofas_weekly.py — daily river flow at each city's chosen GloFAS cell (data/external/glofas/river_choice.csv).
GloFAS stamps the daily mean for day D at 00 UTC of D+1, so the date is shifted back one day here.
Output: data/processed/glofas_city_day.csv  (city, date, flow_m3s, use_in_main_analysis)
"""
import glob, xarray as xr, pandas as pd
ch = pd.read_csv("data/external/glofas/river_choice.csv")
ds = xr.open_mfdataset(sorted(glob.glob("data/external/glofas/all/glofas_all_*.nc")), combine="by_coords")
v = [x for x in ds.data_vars if ds[x].ndim >= 3][0]
out = []
for _, r in ch.iterrows():
    s = ds[v].sel(latitude=r.lat, longitude=r.lon, method="nearest").load().to_series()
    d = pd.DataFrame({"city": r.city, "date": (s.index - pd.Timedelta(days=1)).date, "flow_m3s": s.values.round(3),
                      "use_in_main_analysis": r.use_in_main_analysis})
    out.append(d)
o = pd.concat(out); o.to_csv("data/processed/glofas_city_day.csv", index=False)
print(o.groupby("city").agg(days=("flow_m3s", "size"), first=("date", "min"), last=("date", "max"), mean=("flow_m3s", "mean"), missing=("flow_m3s", lambda x: x.isna().sum())))
