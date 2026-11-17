"""Safety incident counts for analytics without reading the restricted log (FR-CASE-010, RUL-17, 02 10.9,
FR-ANL-001, FR-ANL-003)."""
from datetime import date, datetime, timezone as dt_tz

from analytics import metrics as m
from cases import selectors, services

AT = datetime(2032, 5, 3, 8, tzinfo=dt_tz.utc)


def _log(people, gh, severity, when=AT, narrative="Kwesi Boateng threatened the runner at the gate."):
    return services.log_safety_incident(actor=people["cm"], country=gh, occurred_at=when, severity=severity,
                                        narrative=narrative, persons_named="Kwesi Boateng",
                                        location_note="North gate")


def test_counts_by_country_month_and_severity_only(seeded, people, gh):
    """RUL-17: the selector returns counts by country, month and severity, and nothing else from the log."""
    _log(people, gh, "high")
    _log(people, gh, "high")
    _log(people, gh, "low")
    _log(people, gh, "critical", when=datetime(2032, 6, 1, 0, 30, tzinfo=dt_tz.utc))
    rows = selectors.safety_incident_counts(datetime(2032, 5, 1, tzinfo=dt_tz.utc),
                                            datetime(2032, 7, 1, tzinfo=dt_tz.utc))
    assert rows == [
        {"country": "GH", "month": "2032-05", "severity": "high", "incidents": 2},
        {"country": "GH", "month": "2032-05", "severity": "low", "incidents": 1},
        {"country": "GH", "month": "2032-06", "severity": "critical", "incidents": 1},
    ]
    text = str(rows)
    assert "Kwesi" not in text and "gate" not in text
    assert selectors.safety_incident_counts(datetime(2032, 5, 1, tzinfo=dt_tz.utc),
                                            datetime(2032, 7, 1, tzinfo=dt_tz.utc), ["NG"]) == []


def test_counts_come_from_the_database_function(seeded):
    """02 10.9: analytics reads through safety.incident_counts (SECURITY DEFINER), never the table."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT prosecdef, pg_get_function_result(p.oid) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'safety' AND p.proname = 'incident_counts'")
        secdef, result = cur.fetchone()
    assert secdef is True
    assert "narrative" not in result and "persons_named" not in result and "case_id" not in result


def test_safety_metric_in_analytics(seeded, people, gh, api):
    """FR-ANL-001: the dashboard shows safety incident counts; small groups are blanked for the case manager
    (FR-ANL-003); no narrative or name ever appears."""
    for _ in range(5):
        _log(people, gh, "medium")
    _log(people, gh, "low")
    f = m.Filters(date(2032, 5, 1), date(2032, 5, 31), ["GH"])
    rows = m.METRICS["safety_incidents"].run(f)
    assert {(r["severity"], r["incidents"]) for r in rows} == {("medium", 5), ("low", 1)}
    q = {"date_from": "2032-05-01", "date_to": "2032-05-31", "country": "GH"}
    admin = api(people["admin"]).get("/v1/analytics/metrics/safety_incidents", q).json()
    assert {(r["severity"], r["incidents"]) for r in admin["rows"]} == {("medium", 5), ("low", 1)}
    cm = api(people["cm"]).get("/v1/analytics/metrics/safety_incidents", q).json()
    assert {(r["severity"], r["incidents"]) for r in cm["rows"]} == {("medium", 5), ("low", None)}
    assert "Kwesi" not in str(admin) and "gate" not in str(admin)
