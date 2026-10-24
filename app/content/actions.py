"""Suggested actions per alert level x role x horizon, each with a "because".

Sources the wording follows (verify against the current versions before the
final submission):
- DOH Philippines, leptospirosis health advisories ("avoid wading or swimming
  in floodwater", wear protective boots, consult early if fever follows
  flood exposure).
- PSMID/DOH, "Leptospirosis: Clinical Practice Guidelines" (2010): doxycycline
  post-exposure prophylaxis, with the regimen chosen by a health worker. NO
  doses are shown anywhere.
- PhilHealth leptospirosis case-rate package (hospital admission coverage).

Rules: Warning = pre-position PEP in the top flood-prone barangays, issue
advisories, alert health facilities; Watch = check PEP stock, prepare
messages, monitor the next forecast; Normal = routine surveillance. A Week 3
forecast is less certain, so its actions are preparation only ("prepare",
never "act now"). Each action names why ("because ..."), and a reason seen in
the data (app/logic/reasons.py) can make an action more relevant: it moves up
and its "because" names that reason. Wording: "chance of an outbreak week",
"raised risk"; never "caused by".
"""

from dataclasses import dataclass, field

from app import config

# ACTION +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


@dataclass(frozen=True)
class Action:
    """One suggested action.

    Attributes
    ----------
    text : str
        What to do. "{places}" is replaced by the top flood-prone barangays.
    because : str
        Default reason. "{when}" is replaced by "next week" / "in 2 weeks" ...
    boosts : dict[str, str]
        Reason kind -> a more specific "because". When the city has that
        reason, the action moves up and uses this wording.
    """

    text: str
    because: str
    boosts: dict = field(default_factory=dict)


_HEAVY_RAIN = "heavy rain fell recently, and risk can stay raised for weeks after heavy rain"
_CASES = "reported cases are already close to or above the outbreak line"
_FLOOD = "these barangays have the largest high flood-hazard areas"
_WEEK3 = "a Week 3 forecast is less certain; confirm with next week's forecast before acting"


# HEALTH OFFICE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

HEALTH_OFFICE = {
    "Warning": {
        "act": [
            Action("Pre-position doxycycline PEP per DOH guidelines in the most flood-prone "
                   "barangays{places}.",
                   "an outbreak week is much more likely than usual {when}",
                   {"flood": _FLOOD}),
            Action("Issue public advisories: avoid wading in floodwater, wear boots, see a "
                   "clinic early for fever.",
                   "the chance of an outbreak week is high {when}",
                   {"heavy_rain": _HEAVY_RAIN}),
            Action("Alert health facilities to consider leptospirosis in patients with fever, "
                   "and check beds and referral pathways.",
                   "early treatment prevents severe illness",
                   {"cases": _CASES}),
            Action("Tell the DOH regional epidemiology unit about the Warning.",
                   "the region can send support if reported cases rise"),
        ],
        "prepare": [
            Action("Prepare to pre-position doxycycline PEP in the most flood-prone "
                   "barangays{places}: check stock and transport.",
                   _WEEK3, {"flood": _FLOOD + "; " + _WEEK3}),
            Action("Draft advisory messages so they can go out quickly.",
                   _WEEK3, {"heavy_rain": _HEAVY_RAIN}),
            Action("Check that health facilities are ready to recognise and refer "
                   "leptospirosis.",
                   "it gives facilities time to prepare before a possible rise",
                   {"cases": _CASES}),
        ],
    },
    "Watch": {
        "act": [
            Action("Check doxycycline PEP stock in health centres serving the most "
                   "flood-prone barangays{places}.",
                   "the chance of an outbreak week is raised {when}",
                   {"flood": _FLOOD}),
            Action("Prepare advisory messages so they can go out quickly if the level rises.",
                   "Watch can rise to Warning within 1–2 weeks",
                   {"heavy_rain": _HEAVY_RAIN}),
            Action("Check the next forecast and this week's case reports.",
                   "a rise in reported cases would confirm the raised risk",
                   {"cases": _CASES}),
        ],
    },
    "Normal": {
        "act": [
            Action("Routine surveillance: keep leptospirosis reporting to PIDSR up to date.",
                   "risk is at or below the usual level for this time of year"),
            Action("Keep doxycycline PEP stock at the usual rainy-season level.",
                   "heavy rain can raise risk within 1–2 weeks",
                   {"heavy_rain": _HEAVY_RAIN}),
            Action("Review drainage in the most flood-prone barangays{places} before heavy "
                   "rain.",
                   "these areas flood first",
                   {"flood": _FLOOD}),
        ],
    },
    config.CASE_SIGNAL_LEVEL: {
        "act": [
            Action("Check each week's reported case count, and investigate any week above "
                   "the outbreak line.",
                   "there are too few cases here to forecast a level, so the case count is "
                   "the signal", {"cases": _CASES}),
            Action("Keep reports to PIDSR complete and on time.",
                   "a late or missing report hides the only signal for this city"),
            Action("Keep doxycycline PEP stock ready for flood events.",
                   "heavy rain can still raise risk for the next few weeks",
                   {"heavy_rain": _HEAVY_RAIN}),
        ],
    },
    config.NO_REPORT_LEVEL: {
        "act": [
            Action("Follow up with disease reporting units so PIDSR data are complete.",
                   "this week was flagged as non-reporting"),
            Action("Until reports resume, treat heavy-rain weeks as raised risk.",
                   "the forecast can't be checked against reported cases",
                   {"heavy_rain": _HEAVY_RAIN}),
        ],
    },
    config.NO_FORECAST_LEVEL: {
        "act": [
            Action("Follow routine surveillance.",
                   "there is no forecast for this week"),
            Action("Keep doxycycline PEP stock ready for flood events.",
                   "heavy rain can raise risk for the next few weeks"),
        ],
    },
}


# RESIDENT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

_AVOID = Action("Avoid wading in floodwater, especially with cuts or wounds.",
                "leptospirosis spreads through floodwater",
                {"heavy_rain": "heavy rain fell recently, so floodwater may be around"})
_BOOTS = Action("Wear boots and waterproof gloves if you must go into floodwater.",
                "they protect cuts from contaminated water")
_CLINIC = Action("See a clinic within 2 days if fever or body pain starts after flood "
                 "exposure.",
                 "early treatment works best")
_PLACES = Action("Take extra care in the most flood-prone areas{places}.",
                 "these areas flood first", {"flood": _FLOOD})

RESIDENT = {
    "Warning": {
        "act": [_AVOID, _BOOTS, _CLINIC, _PLACES,
                Action("Follow your city health office's advisories.",
                       "the chance of an outbreak week is high {when}")],
        "prepare": [
            Action("Get boots and gloves ready and plan to avoid floodwater.",
                   _WEEK3, {"heavy_rain": _HEAVY_RAIN}),
            _CLINIC, _PLACES,
        ],
    },
    "Watch": {
        "act": [_AVOID, _CLINIC,
                Action("Watch for your city health office's advisories this week.",
                       "the chance of an outbreak week is raised {when}"),
                _PLACES],
    },
    "Normal": {
        "act": [
            Action("Keep drains and surroundings clean so rainwater does not pool.",
                   "standing water can carry the bacteria"),
            Action("Keep boots and gloves where you can reach them in the rainy season.",
                   "risk rises after heavy rain", {"heavy_rain": _HEAVY_RAIN}),
            _CLINIC,
        ],
    },
}
for _level in (config.CASE_SIGNAL_LEVEL, config.NO_REPORT_LEVEL, config.NO_FORECAST_LEVEL):
    RESIDENT[_level] = {"act": [_AVOID, _BOOTS, _CLINIC]}


# FLOOD ALERT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Shown while a health office's Flood alert is on (config.FLOOD_ALERT_WEEKS),
# beside the forecast level, which does not change.
FLOOD_BECAUSE = ("a major flood was reported; the model can't foresee sudden catastrophic "
                 "floods (see Washi)")
FLOOD_ACTIONS = (
    Action("Issue flood advisories now: avoid wading in floodwater, wear boots, see a clinic "
           "early for fever.", FLOOD_BECAUSE),
    Action("Get doxycycline PEP ready per DOH guidelines for people exposed to floodwater"
           "{places}.", FLOOD_BECAUSE),
    Action("Alert clinics and hospitals to consider leptospirosis in anyone with fever after "
           "flood exposure.", FLOOD_BECAUSE),
)


def flood_actions(barangays=()):
    """The Flood alert's actions, each with its "because".

    Parameters
    ----------
    barangays : sequence of str
        Most flood-prone barangays, named in "{places}".

    Returns
    -------
    list[dict]
        [{"text", "because"}] in FLOOD_ACTIONS order.
    """
    places = _places(barangays)
    return [{"text": a.text.replace("{places}", places), "because": a.because}
            for a in FLOOD_ACTIONS]


# SELECTION ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# How many barangay names go into one action line.
NAMED_PLACES = 3


def _places(barangays):
    """" (A, B and C)" for the first NAMED_PLACES names, or "" if none.

    Parameters
    ----------
    barangays : sequence of str

    Returns
    -------
    str
    """
    names = [str(b) for b in list(barangays)[:NAMED_PLACES]]
    if not names:
        return ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f" ({joined})"


def _when(horizon):
    """ "next week" / "in 2 weeks" / "in 3 weeks" (config.HORIZON_NAMES).

    Parameters
    ----------
    horizon : int

    Returns
    -------
    str
    """
    return config.HORIZON_NAMES.get(horizon, f"In {horizon} weeks").lower()


def select_actions(level, role, horizon=1, reasons=(), barangays=(), limit=None):
    """The suggested actions for one city, most relevant first.

    Parameters
    ----------
    level : str | None
        Shown alert level (config.DISPLAY_LEVELS); None counts as Case signal only.
    role : str
        "Resident" or "Health office"; unknown roles get the resident list.
    horizon : int
        1-3. Week 3 Warnings use the preparation-only list.
    reasons : sequence of Reason
        app.logic.reasons.city_reasons output. An action whose `boosts`
        names one of these reason kinds moves up and says that reason.
    barangays : sequence of str
        Most flood-prone barangays, named in "{places}".
    limit : int | None
        Keep only the first `limit` actions (the drawer's "Do now" uses 3).

    Returns
    -------
    list[dict]
        [{"text": ..., "because": ...}], never empty. Order: boosted actions
        first (in their listed order), then the rest.
    """
    level = level if level in config.DISPLAY_LEVELS else config.CASE_SIGNAL_LEVEL
    table = HEALTH_OFFICE if role == "Health office" else RESIDENT
    lists = table[level]
    stage = "prepare" if horizon >= 3 and "prepare" in lists else "act"
    kinds = {r.kind for r in reasons}
    fill = {"{places}": _places(barangays), "{when}": _when(horizon)}

    def render(action):
        hit = next((k for k in action.boosts if k in kinds), None)
        because = action.boosts[hit] if hit else action.because
        if stage == "act" and horizon >= 3 and level in config.PRIORITY_LEVELS:
            because += " (Week 3 is less certain: prepare, then confirm next week)"
        text = action.text
        for key, value in fill.items():
            text, because = text.replace(key, value), because.replace(key, value)
        return hit is not None, {"text": text, "because": because}

    rendered = [render(a) for a in lists[stage]]
    ordered = [r for boosted, r in rendered if boosted] + \
              [r for boosted, r in rendered if not boosted]
    return ordered[:limit] if limit else ordered
