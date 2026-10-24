#!/usr/bin/env python3
"""
07c_glofas_rivers.py  —  Stage 7c, step 1: pick each city's river in GloFAS and check it against known floods.

For each city:
  * "main river" = the GloFAS cell with the highest average flow among cells inside the city or within
    ~2 km of its boundary (the river that actually flows through or along the city);
  * "largest nearby river" = the highest-flow cell within ~15 km (for comparison; it can be a bigger
    neighbouring river that does not pass through the city).
Sanity check: where each chosen cell's flow ranked on the dates of well-known floods.
GloFAS stamps each daily average at 00 UTC of the next day, so the flow for day D is read at D+1
(and the check takes the higher of D+1 and D+2, since river peaks lag rainfall by up to a day).

Inputs : data/external/glofas/all/glofas_all_<year>.nc, data/raw/brgy_geography.csv,
         data/external/glofas/brgy_city.csv
Outputs: output/stage7/glofas_river_cells.csv, output/stage7/glofas_flood_checks.csv,
         output/stage7/figs/glofas_rivers.png
Run from the LeapTo folder:  python3 R/07c_glofas_rivers.py
"""
import glob, os
import numpy as np, pandas as pd, xarray as xr
from shapely import wkt
from shapely.ops import unary_union
from shapely.geometry import Point
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

OUT = "output/stage7"; FIG = os.path.join(OUT, "figs"); os.makedirs(FIG, exist_ok=True)
NEAR_DEG, FAR_DEG = 0.02, 0.135          # ~2 km and ~15 km
CITIES = ["Dagupan", "Palayan", "Navotas", "Mandaluyong", "Muntinlupa", "Legazpi",
          "Iloilo", "Mandaue", "Tacloban", "Zamboanga", "Cagayan de Oro", "Davao"]
# Well-known floods (local date of the main flooding) used only as a sanity check
FLOODS = [("Cagayan de Oro", "Typhoon Washi (Sendong)", "2011-12-16"),
          ("Mandaluyong", "Typhoon Ketsana (Ondoy)", "2009-09-26"),
          ("Navotas", "Typhoon Ketsana (Ondoy)", "2009-09-26"),
          ("Mandaluyong", "2012 southwest monsoon (Habagat) floods", "2012-08-07"),
          ("Iloilo", "Typhoon Fengshen (Frank)", "2008-06-21"),
          ("Dagupan", "Typhoon Parma (Pepeng)", "2009-10-08")]

files = sorted(glob.glob("data/external/glofas/all/glofas_all_*.nc"))
ds = xr.open_mfdataset(files, combine="by_coords") if len(files) > 1 else xr.open_dataset(files[0])
var = [v for v in ds.data_vars if ds[v].ndim >= 3][0]
q = ds[var].load()
years = sorted({int(os.path.basename(f)[11:15]) for f in files})
print(f"{len(files)} years ({years[0]}-{years[-1]}), {q.sizes}")
mean = q.mean("valid_time")

geo = pd.read_csv("data/raw/brgy_geography.csv", usecols=["adm4_pcode", "geometry"])
bc = pd.read_csv("data/external/glofas/brgy_city.csv")
geo = geo.merge(bc, on="adm4_pcode")
polys = {c: unary_union([wkt.loads(g) for g in geo.loc[geo.city == c, "geometry"]]) for c in CITIES}

lat = mean.latitude.values; lon = mean.longitude.values
LON, LAT = np.meshgrid(lon, lat)
rows = []
for c in CITIES:
    poly = polys[c]; near = poly.buffer(NEAR_DEG); far = poly.buffer(FAR_DEG)
    W, S, E, N = far.bounds
    sel = (LON >= W) & (LON <= E) & (LAT >= S) & (LAT <= N)
    cand = [(i, j) for i, j in zip(*np.where(sel))]
    inn = [(i, j) for i, j in cand if near.contains(Point(LON[i, j], LAT[i, j]))]
    out = [(i, j) for i, j in cand if far.contains(Point(LON[i, j], LAT[i, j]))]
    m = mean.values
    pick = lambda cells: max(cells, key=lambda ij: np.nan_to_num(m[ij], nan=-1)) if cells else None
    a, b = pick(inn), pick(out)
    for kind, ij in [("main river (in or next to city)", a), ("largest river within ~15 km", b)]:
        if ij is None:
            continue
        rows.append(dict(city=c, kind=kind, lat=round(float(lat[ij[0]]), 3), lon=round(float(lon[ij[1]]), 3),
                         mean_flow_m3s=round(float(m[ij]), 1),
                         p99_flow_m3s=round(float(np.nanpercentile(q.values[:, ij[0], ij[1]], 99)), 1),
                         max_flow_m3s=round(float(np.nanmax(q.values[:, ij[0], ij[1]])), 1),
                         cells_in_city=len(inn), same_as_main=(ij == a)))
cells = pd.DataFrame(rows)
cells.to_csv(os.path.join(OUT, "glofas_river_cells.csv"), index=False)
print(cells.to_string(index=False))

# ---- sanity check against known floods ------------------------------------------------------
chk = []
main = cells[cells.kind.str.startswith("main")].set_index("city")
for c, name, day in FLOODS:
    if c not in main.index:
        continue
    r = main.loc[c]
    s = q.sel(latitude=r.lat, longitude=r.lon, method="nearest").to_series()
    d = pd.Timestamp(day)
    if not (s.index.min() <= d <= s.index.max()):
        continue
    v = s.loc[d + pd.Timedelta(days=1): d + pd.Timedelta(days=2)].max()
    pct = 100 * (s < v).mean()
    yr = s[s.index.year == (d + pd.Timedelta(days=1)).year]
    chk.append(dict(city=c, event=name, date=day, flow_m3s=round(float(v), 1), percentile_all_days=round(pct, 2),
                    rank_in_its_year=int((yr > v).sum() + 1), typical_flow_m3s=round(float(s.median()), 1)))
chk = pd.DataFrame(chk)
chk.to_csv(os.path.join(OUT, "glofas_flood_checks.csv"), index=False)
print(chk.to_string(index=False))

# ---- map -------------------------------------------------------------------------------------
fig, axes = plt.subplots(3, 4, figsize=(16, 12.6))
vals = mean.values
norm = LogNorm(vmin=1, vmax=max(10, np.nanpercentile(vals, 99.9)))
for ax, c in zip(axes.flat, CITIES):
    poly = polys[c]; far = poly.buffer(FAR_DEG); W, S, E, N = far.bounds
    ax.pcolormesh(lon, lat, np.where(vals > 0, vals, np.nan), norm=norm, cmap="Blues", shading="nearest")
    for g in (poly.geoms if poly.geom_type == "MultiPolygon" else [poly]):
        x, y = g.exterior.xy; ax.plot(x, y, color="#0b0b0b", lw=1.1)
    sub = cells[cells.city == c]
    for _, r in sub.iterrows():
        if r.kind.startswith("main"):
            ax.plot(r.lon, r.lat, "o", ms=10, mfc="#eb6834", mec="white", mew=1.5, zorder=5)
        elif not r.same_as_main:
            ax.plot(r.lon, r.lat, "o", ms=10, mfc="none", mec="#eb6834", mew=2, zorder=5)
    m = sub[sub.kind.str.startswith("main")]
    title = c if m.empty else f"{c}\nmain river cell: {m.iloc[0].mean_flow_m3s:.0f} m³/s on average"
    ax.set_title(title, fontsize=10.5, loc="left")
    ax.set_xlim(W, E); ax.set_ylim(S, N); ax.set_aspect("equal"); ax.tick_params(labelsize=7.5)
fig.suptitle(f"GloFAS river cells chosen for each city (average river flow {years[0]}–{years[-1]}). "
             "Filled orange = main river in or next to the city (used); open orange = a larger river within ~15 km (not used). "
             "Black = city boundary", fontsize=11.5, x=0.01, ha="left")
sm = plt.cm.ScalarMappable(norm=norm, cmap="Blues"); sm.set_array([])
fig.colorbar(sm, ax=axes, shrink=0.5, label="Average river flow (m³/s, log scale)")
fig.savefig(os.path.join(FIG, "glofas_rivers.png"), dpi=130, bbox_inches="tight", facecolor="white")
print("saved", os.path.join(FIG, "glofas_rivers.png"))
