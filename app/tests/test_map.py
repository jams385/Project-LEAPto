"""Tests for the map figure: quick views, the Philippines pan limit, labels, hint."""

from html import unescape

import pandas as pd
import pytest

from app import config
from app.components.all_cities import chance_figure
from app.components.city_map import build_map, map_label
from app.components.hover import city_hovers
from app.components.legend import legend_html

GEOJSON = {"type": "FeatureCollection", "features": []}


@pytest.fixture
def snap():
    return pd.DataFrame({
        "adm3_pcode": ["PH063022000", "PH097332000"], "city_name": ["Iloilo City", "Zamboanga"],
        "alert_level": ["Warning", "Normal"], "lat": [10.72, 6.92], "lon": [122.56, 122.08],
        "latest_cases": [9.0, float("nan")], "rain_week_mm": [109.0, 20.0],
        "hazard_pct": [6.0, 3.0],
    })


def figure(snap, **kwargs):
    args = dict(layer="Risk", selected=None)
    args.update(kwargs)
    return build_map(snap, GEOJSON, {"PH063022000": 10.5}, **args)


@pytest.mark.parametrize("view", list(config.MAP_VIEWS))
def test_quick_views_set_centre_and_zoom(snap, view):
    m = figure(snap, view=view).layout.map
    spot = config.MAP_VIEWS[view]
    assert (m.center.lat, m.center.lon, m.zoom) == (spot["lat"], spot["lon"], spot["zoom"])


def test_map_is_limited_to_the_philippines(snap):
    bounds = figure(snap).layout.map.bounds
    assert (bounds.west, bounds.east, bounds.south, bounds.north) == (105.0, 140.0, -1.0, 25.0)
    # every quick view's centre lies inside the box
    b = config.MAP_BOUNDS
    for spot in config.MAP_VIEWS.values():
        assert b["west"] < spot["lon"] < b["east"] and b["south"] < spot["lat"] < b["north"]


def test_selected_city_zooms_in_unless_a_view_is_chosen(snap):
    city = figure(snap, selected="PH063022000").layout.map
    assert (city.center.lat, city.zoom) == (10.72, 10.5)
    region = figure(snap, selected="PH063022000", view="Mindanao").layout.map
    assert region.zoom == config.MAP_VIEWS["Mindanao"]["zoom"]
    default = figure(snap).layout.map            # nothing selected, no view
    assert default.zoom == config.MAP_VIEWS[config.DEFAULT_MAP_VIEW]["zoom"]


def test_cities_are_labelled_and_hint_shows_only_when_asked(snap):
    fig = figure(snap, hint=config.MAP_HINT)
    cities = fig.data[-1]
    assert list(cities.text) == ["Iloilo", "Zamboanga"] and "text" in cities.mode
    texts = [a.text for a in fig.layout.annotations]
    assert texts == [config.MAP_HINT]
    assert not figure(snap).layout.annotations
    assert cities.hovertemplate == "%{hovertext}<extra></extra>"


def test_there_is_no_mode_chip_and_only_the_hint_annotation(snap):
    assert not figure(snap).layout.annotations
    assert [a.text for a in figure(snap, hint=config.MAP_HINT).layout.annotations] == [
        config.MAP_HINT]
    assert not hasattr(config, "MAP_LAYER_TITLES")


def test_satellite_is_the_only_basemap_and_is_credited(snap):
    assert not hasattr(config, "BASEMAPS") and not hasattr(config, "BASEMAP_SPECS")
    layers = figure(snap).layout.map.layers
    assert len(layers) == 1 and "World_Imagery" in layers[0].source[0]
    assert "Esri" in layers[0].sourceattribution


def test_selected_city_gets_a_larger_solid_neutral_marker_and_no_home_ring(snap):
    plain = figure(snap)
    chosen = figure(snap, selected="PH063022000")
    assert len(chosen.data) == len(plain.data) + 1
    ring = chosen.data[-2]
    assert ring.marker.color == config.MAP_INK and ring.marker.opacity == 1
    assert ring.marker.size == config.MAP_MARKER_SIZE + config.MAP_SELECTED_RING_EXTRA
    assert not hasattr(config, "MAP_HOME_RING_SIZE") and not hasattr(config, "DEFAULT_HOME_CITY")


def test_risk_colours_by_level_and_the_other_layers_use_their_ramps(snap):
    risk = figure(snap, layer="Risk")
    assert list(risk.data[-1].marker.color) == [config.LEVEL_COLORS["Warning"],
                                                config.LEVEL_COLORS["Normal"]]
    for layer, scale, values in (("Rainfall", config.RAINFALL_COLORSCALE, [109.0, 20.0]),
                                 ("Flood hazard", config.FLOOD_COLORSCALE, [6.0, 3.0])):
        fig = figure(snap, layer=layer)
        ramp = next(t for t in fig.data if t.type == "choroplethmap")
        assert [list(c) for c in ramp.colorscale] == [list(c) for c in scale]
        assert list(ramp.z) == values                  # polygons coloured by the layer's value
        assert fig.data[-1].marker.color == "#E8EEF5"  # neutral markers
        assert fig.data[-1].marker.size == config.MAP_MARKER_SIZE


def test_legend_shows_level_colours_for_risk_and_a_ramp_for_the_other_layers(snap):
    risk = legend_html(snap, "Risk")
    for level in ("Warning", "Watch", "Normal", config.CASE_SIGNAL_LEVEL):
        assert config.LEVEL_COLORS[level] in risk
    assert "gradient" not in risk and "Your city" not in risk and "Selected" not in risk
    rain, flood = legend_html(snap, "Rainfall"), legend_html(snap, "Flood hazard")
    assert "leap-key-gradient" in rain and "Rain last week" in rain and "109 mm" in rain
    assert "leap-key-gradient" in flood and "flood-hazard" in flood and "6%" in flood


@pytest.mark.parametrize("name, label", [("City of Navotas", "Navotas"),
                                         ("Cagayan de Oro City", "Cagayan de Oro"),
                                         ("Mandaue", "Mandaue")])
def test_map_label(name, label):
    assert map_label(name) == label


def test_clicking_a_view_again_resets_the_view(snap):
    first = figure(snap, view="Luzon", revision=1).layout.uirevision
    again = figure(snap, view="Luzon", revision=2).layout.uirevision
    assert first != again


def test_map_uses_the_normal_cursor():
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "maplibregl-canvas" not in css          # no custom map cursor rule
    assert "cursor: url(" not in css               # no image cursor anywhere


def test_city_hover_shows_the_wanted_lines_and_never_nan(snap):
    snap = snap.assign(outbreak_prob=[0.30, 0.01], confidence=["standard", "standard"],
                       rain_status=["Wetter than usual", None])
    texts = city_hovers(snap, 0.07)
    first, second = texts
    assert first.startswith("<b>Iloilo City</b>") and "Warning" in first
    assert config.LEVEL_COLORS["Warning"] in first and "× a usual week" in first
    assert "Rain last week: 109 mm (wetter than usual)" in first
    assert "Reported cases, latest week: 9" in first and first.endswith("<i>Click for details</i>")
    assert "Reported cases" not in second                   # missing value: no line, no "nan"
    for text in texts:
        assert "nan" not in text.lower() and "None" not in text


def test_case_signal_and_lower_confidence_get_their_note_instead_of_a_multiplier(snap):
    snap = snap.assign(outbreak_prob=[0.30, 0.30], confidence=["case_signal", "lower"],
                       alert_level=["Case signal only", "Warning"])
    first, second = city_hovers(snap, 0.07)
    assert "Too few cases to forecast" in first and "× a usual week" not in first
    assert "Lower confidence" in second and "× a usual week" not in second


def test_hover_style_is_shared_by_the_map_and_the_charts(snap):
    fig = figure(snap)
    assert fig.layout.hoverlabel.align == "left" and fig.layout.hoverlabel.bgcolor == "#0B1E33"
    assert fig.layout.hoverlabel.namelength == 0
    tmpl = chance_figure(pd.DataFrame({"City": ["A"], "Level": ["Watch"], "Chance (%)": [12.0]}))
    assert tmpl.layout.hoverlabel.bgcolor == fig.layout.hoverlabel.bgcolor
    assert all(t.hovertemplate.endswith("<extra></extra>") for t in tmpl.data)
