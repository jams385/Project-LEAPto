"""Generate the static SVG assets used by the landing and loading screens.

    python scripts/make_static_svgs.py

Streamlit's HTML sanitiser strips inline <svg>, so the animated waves and the
feature-chip icons are served as files from app/static/ and shown with <img>
(CSS animations inside an SVG image still run). Writes:
    app/static/waves.svg        three glowing sine waves, CSS-animated
    app/static/icon_chart.svg   "City risk updates" chip icon
    app/static/icon_bell.svg    "Flood alerts" chip icon
    app/static/icon_shield.svg  "Safety steps" chip icon
"""

import math
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

# (stroke colour, amplitude px, period px, phase rad, seconds per cycle)
WAVES = (
    ("#2F80C0", 46, 520, 0.0, 6.0),
    ("#2EC4B6", 38, 460, 1.9, 4.6),
    ("#E8EEF5", 30, 600, 3.6, 7.5),
)

ICON_STROKE = "#E8EEF5"
ICONS = {
    "icon_chart.svg": '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
    "icon_bell.svg": '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/>'
                     '<path d="M10 20a2 2 0 0 0 4 0"/>',
    "icon_shield.svg": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>'
                       '<path d="M9 12l2 2 4-4"/>',
}


# BUILDERS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def wave_path(amplitude, period, phase, width=2400, mid=100, step=12):
    """SVG path data for one sine wave.

    Parameters
    ----------
    amplitude, period : float
        In SVG units (px).
    phase : float
        Radians.
    width : int
        Path length: twice the 1200-unit viewBox so a translate of one period
        loops seamlessly.
    mid : int
        Vertical centre line.
    step : int
        Sampling interval in px.

    Returns
    -------
    str
        "M x,y L x,y ..." path data.
    """
    pts = [f"{x},{mid + amplitude * math.sin(2 * math.pi * x / period + phase):.1f}"
           for x in range(0, width + step, step)]
    return "M " + " L ".join(pts)


def waves_svg():
    """The animated waves SVG document.

    Returns
    -------
    str
        Standalone SVG with embedded CSS keyframes; motion stops under
        prefers-reduced-motion.
    """
    css, paths = [], []
    for i, (color, amp, period, phase, secs) in enumerate(WAVES):
        css.append(f"@keyframes w{i} {{ to {{ transform: translateX(-{period}px); }} }} "
                   f".w{i} {{ animation: w{i} {secs}s linear infinite; }}")
        paths.append(f'<path class="w{i}" d="{wave_path(amp, period, phase)}" stroke="{color}" '
                     'stroke-width="3" fill="none" stroke-linecap="round"/>')
    style = (" ".join(css) + " path { filter: drop-shadow(0 0 5px rgba(120,200,255,0.6)); } "
             "@media (prefers-reduced-motion: reduce) { path { animation: none !important; } }")
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 200" '
            f'preserveAspectRatio="none"><style>{style}</style>{"".join(paths)}</svg>\n')


def icon_svg(body):
    """A 24 x 24 outline icon.

    Parameters
    ----------
    body : str
        Inner SVG elements.

    Returns
    -------
    str
    """
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" '
            f'fill="none" stroke="{ICON_STROKE}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>\n')


# MAIN +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def main():
    """Write all SVG assets to app/static/.

    Returns
    -------
    None
    """
    (STATIC / "waves.svg").write_text(waves_svg(), encoding="utf-8")
    for name, body in ICONS.items():
        (STATIC / name).write_text(icon_svg(body), encoding="utf-8")
    print(f"wrote waves.svg and {len(ICONS)} icons to {STATIC}")


if __name__ == "__main__":
    main()
