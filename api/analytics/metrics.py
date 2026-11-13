"""The metric tables behind the operating dashboard (FR-ANL-001, 01 section A9) and the
day-90 review (docs/validation-plan.md sections 5 and 6).

Every metric is a read-only query over another module's tables: ORM aggregates
where the database can do the work, a little Python where a figure needs the
country's working-day calendar (turnaround, release clock) or a median.

Rules every metric follows:

- Rows are aggregates. No metric returns a name, an email, an id of a person
  or any free text a person wrote (FR-ANL-003). The only personal-data export,
  the client register, goes through DPR's two-person bulk export (services.py).
- Months are calendar months in UTC (`YYYY-MM`).
- Money is summed per currency and never converted. Values are strings with
  two decimals, as everywhere in the API.
- Every target is a working assumption from the validation plan, not verified
  data, and can be changed per country in the configuration
  (`analytics.day90_targets`).
- Health and care readings, concerns and insurance applications are never
  read (TR-12, 02 section 10.9); care and insurance metrics count statuses only.
  The safety incident log is not readable by analytics by design (RUL-17);
  safety incidents are reported from that log by the people named on it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from math import floor
from typing import Callable
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth

UTC = dt_timezone.utc
LINES = ("property", "family", "projects")
ESCROW_LINE = {"purchase": "property", "construction": "property", "offplan": "property", "repair": "property",
               "project_fund": "projects", "event": "projects", "held_funds": "family"}
CENT = Decimal("0.01")


# --------------------------------------------------------------------------- filters

@dataclass
class Filters:
    """What the viewer asked for, already limited to the countries they may see.
    `countries` None means every country."""

    date_from: date
    date_to: date
    countries: list[str] | None = None
    line: str = ""
    tier: str = ""

    @property
    def start(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=UTC)

    @property
    def end(self) -> datetime:  # exclusive
        return datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=UTC)

    def as_dict(self) -> dict:
        return {"date_from": self.date_from.isoformat(), "date_to": self.date_to.isoformat(),
                "countries": self.countries, "line": self.line, "tier": self.tier}


@dataclass(frozen=True)
class Metric:
    name: str
    title: str
    fn: Callable[[Filters], list[dict]]
    dims: tuple
    values: tuple
    base: str | None            # the count that sets the group size for small-number suppression
    line: str | None = None     # fixed product family; None: the metric filters by line itself
    uses: tuple = ()            # which of line and tier the metric applies ("line", "tier")
    source: str = ""
    description: str = ""
    personal: bool = False

    @property
    def columns(self) -> list[str]:
        return [*self.dims, *self.values]

    def run(self, f: Filters) -> list[dict]:
        if f.line and self.line and f.line != self.line:
            return []
        return self.fn(f)


METRICS: dict[str, Metric] = {}


def metric(name, title, *, dims, values, base, line=None, uses=(), source="", description=""):
    def deco(fn):
        METRICS[name] = Metric(name=name, title=title, fn=fn, dims=tuple(dims), values=tuple(values), base=base,
                               line=line, uses=tuple(uses), source=source, description=description)
        return fn

    return deco


# --------------------------------------------------------------------------- helpers

def _window(qs, f: Filters, at: str, country: str = "country"):
    qs = qs.filter(**{f"{at}__gte": f.start, f"{at}__lt": f.end})
    if f.countries is not None:
        qs = qs.filter(**{f"{country}__code__in": f.countries})
    return qs


def _date_window(qs, f: Filters, on: str, country: str = "country"):
    qs = qs.filter(**{f"{on}__gte": f.date_from, f"{on}__lte": f.date_to})
    if f.countries is not None:
        qs = qs.filter(**{f"{country}__code__in": f.countries})
    return qs


def _month(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(UTC) if value.tzinfo else value
    return f"{value.year:04d}-{value.month:02d}"


def money(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(value).quantize(CENT))


def pct(part, whole) -> float | None:
    if not whole:
        return None
    return round(100.0 * float(part) / float(whole), 1)


def percentile(values, p: float):
    """Linear interpolation between closest ranks, as PostgreSQL's percentile_cont."""
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo = floor(k)
    hi = min(lo + 1, len(v) - 1)
    return round(float(v[lo] + (v[hi] - v[lo]) * (k - lo)), 1)


def _kinds_for_line(line: str) -> list[str]:
    from orders.catalogue import PRODUCTS

    return [k for k, p in PRODUCTS.items() if p.line == line]


def order_line(kind: str) -> str:
    from orders.catalogue import PRODUCTS

    p = PRODUCTS.get(kind)
    return p.line if p else ""


class _Countries:
    """Country rows by code, for time zones and working-day calendars."""

    def __init__(self):
        self._c = {}

    def get(self, code):
        if code not in self._c:
            from countries.models import Country

            self._c[code] = Country.objects.filter(code=code).first()
        return self._c[code]

    def local_date(self, code, dt: datetime) -> date:
        c = self.get(code)
        try:
            tz = ZoneInfo(c.timezone) if c and c.timezone else UTC
        except Exception:  # noqa: BLE001 - an unknown zone name falls back to UTC
            tz = UTC
        return dt.astimezone(tz).date()

    def working_days(self, code, start: datetime, end: datetime) -> int:
        from countries.selectors import working_days_between

        c = self.get(code)
        return working_days_between(c, self.local_date(code, start), self.local_date(code, end))


def _rows(qs, keys: dict, values: dict) -> list[dict]:
    """Rename ORM `.values()` keys to metric column names and format values."""
    out = []
    for r in qs:
        row = {}
        for col, src in keys.items():
            v = r[src]
            row[col] = _month(v) if col == "month" else (v if v is not None else "")
        for col, fmt in values.items():
            row[col] = fmt(r[col]) if fmt else (r[col] or 0)
        out.append(row)
    return out


def _sort(rows, dims):
    return sorted(rows, key=lambda r: tuple(str(r.get(d, "")) for d in dims))


# --------------------------------------------------------------------------- orders and reports

@metric("orders_paid", "Paid orders", dims=("month", "country", "line", "kind", "tier", "currency"),
        values=("orders", "value", "refunded"), base="orders", uses=("line", "tier"), source="Orders",
        description="Orders paid each month by product, tier and country; refunded orders counted apart.")
def orders_paid(f: Filters) -> list[dict]:
    from orders.models import Order

    qs = _window(Order.objects.filter(status__in=["paid", "refunded"]), f, "paid_at")
    if f.line:
        qs = qs.filter(kind__in=_kinds_for_line(f.line))
    if f.tier:
        qs = qs.filter(tier=f.tier)
    qs = (qs.annotate(m=TruncMonth("paid_at")).values("m", "country__code", "kind", "tier", "price_currency")
          .annotate(orders=Count("id", filter=Q(status="paid")), value=Sum("price_amount", filter=Q(status="paid")),
                    refunded=Count("id", filter=Q(status="refunded"))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "kind": "kind", "tier": "tier",
                      "currency": "price_currency"},
                 {"orders": None, "value": lambda v: money(v or 0), "refunded": None})
    for r in rows:
        r["line"] = order_line(r["kind"])
    return _sort(rows, METRICS["orders_paid"].dims)


def released_reports(f: Filters):
    """First issues of released reports (a correction is not a new report)."""
    from reports.models import Report

    qs = _window(Report.objects.filter(status__in=["released", "superseded"], supersedes__isnull=True), f,
                 "released_at")
    if f.tier:
        qs = qs.filter(case__order__tier=f.tier)
    return qs


@metric("reports_released", "Reports released", dims=("month", "country", "product_line", "tier"),
        values=("reports", "seller_paid", "red", "amber", "green"), base="reports", line="property",
        uses=("line", "tier"), source="Reports",
        description="Verification reports released each month (first issue only), with the verdicts.")
def reports_released(f: Filters) -> list[dict]:
    qs = (released_reports(f).annotate(m=TruncMonth("released_at"))
          .values("m", "country__code", "case__product_line", "case__order__tier")
          .annotate(reports=Count("id"), seller_paid=Count("id", filter=Q(case__order__kind="listing_verification")),
                    red=Count("id", filter=Q(overall_verdict="red")),
                    amber=Count("id", filter=Q(overall_verdict="amber")),
                    green=Count("id", filter=Q(overall_verdict="green"))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "product_line": "case__product_line",
                      "tier": "case__order__tier"},
                 {"reports": None, "seller_paid": None, "red": None, "amber": None, "green": None})
    return _sort(rows, METRICS["reports_released"].dims)


@metric("verdict_mix", "Verdict mix", dims=("country", "product_line"),
        values=("reports", "red", "amber", "green", "red_pct", "amber_pct", "green_pct"), base="reports",
        line="property", uses=("line", "tier"), source="Reports",
        description="Share of red, amber and green verdicts over the period. A high red share is a selling point.")
def verdict_mix(f: Filters) -> list[dict]:
    qs = (released_reports(f).values("country__code", "case__product_line")
          .annotate(reports=Count("id"), red=Count("id", filter=Q(overall_verdict="red")),
                    amber=Count("id", filter=Q(overall_verdict="amber")),
                    green=Count("id", filter=Q(overall_verdict="green"))))
    rows = []
    for r in qs:
        n = r["reports"]
        rows.append({"country": r["country__code"], "product_line": r["case__product_line"], "reports": n,
                     "red": r["red"], "amber": r["amber"], "green": r["green"], "red_pct": pct(r["red"], n),
                     "amber_pct": pct(r["amber"], n), "green_pct": pct(r["green"], n)})
    return _sort(rows, METRICS["verdict_mix"].dims)


def turnaround_samples(f: Filters) -> list[tuple]:
    """(country, month, product_line, working_days, calendar_days) for each released report, from the order's
    payment to the report's release."""
    cs = _Countries()
    out = []
    for code, released_at, paid_at, line in released_reports(f).filter(case__order__paid_at__isnull=False) \
            .values_list("country__code", "released_at", "case__order__paid_at", "case__product_line"):
        out.append((code, _month(released_at), line, cs.working_days(code, paid_at, released_at),
                    (released_at - paid_at).total_seconds() / 86400.0))
    return out


@metric("turnaround", "Turnaround, payment to report", dims=("month", "country", "product_line"),
        values=("reports", "median_working_days", "p90_working_days", "max_working_days", "median_calendar_days"),
        base="reports", line="property", uses=("line", "tier"), source="Orders and reports",
        description="Working days in the country's calendar from the order's payment to the report's release. "
                    "Targets in the validation plan are assumptions.")
def turnaround(f: Filters) -> list[dict]:
    groups = defaultdict(list)
    for code, month, line, wd, cd in turnaround_samples(f):
        groups[(month, code, line)].append((wd, cd))
    rows = []
    for (month, code, line), xs in groups.items():
        wds = [x[0] for x in xs]
        rows.append({"month": month, "country": code, "product_line": line, "reports": len(xs),
                     "median_working_days": percentile(wds, 0.5), "p90_working_days": percentile(wds, 0.9),
                     "max_working_days": max(wds), "median_calendar_days": percentile([x[1] for x in xs], 0.5)})
    return _sort(rows, METRICS["turnaround"].dims)


def cost_samples(f: Filters) -> list[dict]:
    """Released reports whose case has cost entries, with the cost and the order price per currency."""
    from cases.models import CostItem

    reports = list(released_reports(f).values(
        "case_id", "country__code", "released_at", "case__order__price_amount", "case__order__price_currency",
        "case__order__local_price_amount", "case__order__local_price_currency"))
    by_case = {r["case_id"]: r for r in reports}
    costs = defaultdict(lambda: Decimal("0"))
    for row in CostItem.objects.filter(case_id__in=list(by_case)).values("case_id", "currency") \
            .annotate(total=Sum("amount")):
        costs[(row["case_id"], row["currency"])] += row["total"] or 0
    out = []
    for (case_id, cur), total in costs.items():
        r = by_case[case_id]
        price = None
        if r["case__order__price_currency"] == cur:
            price = r["case__order__price_amount"]
        elif r["case__order__local_price_currency"] == cur:
            price = r["case__order__local_price_amount"]
        out.append({"country": r["country__code"], "month": _month(r["released_at"]), "currency": cur,
                    "cost": total, "price": price})
    return out


@metric("cost_per_report", "Cost per report", dims=("month", "country", "currency"),
        values=("reports_costed", "total_cost", "cost_per_report", "price_total", "cost_share_pct",
                "gross_margin_pct"), base="reports_costed", line="property", uses=("line", "tier"),
        source="Case costs entered by operations and by PRO",
        description="Lawyer, surveyor, runner, fees and travel per released report, against the price in the "
                    "same currency.")
def cost_per_report(f: Filters) -> list[dict]:
    groups = defaultdict(list)
    for s in cost_samples(f):
        groups[(s["month"], s["country"], s["currency"])].append(s)
    rows = []
    for (month, code, cur), xs in groups.items():
        total = sum((x["cost"] for x in xs), Decimal("0"))
        priced = [x for x in xs if x["price"]]
        price_total = sum((x["price"] for x in priced), Decimal("0"))
        share = pct(sum((x["cost"] for x in priced), Decimal("0")), price_total)
        rows.append({"month": month, "country": code, "currency": cur, "reports_costed": len(xs),
                     "total_cost": money(total), "cost_per_report": money(total / len(xs)),
                     "price_total": money(price_total) if priced else None, "cost_share_pct": share,
                     "gross_margin_pct": None if share is None else round(100.0 - share, 1)})
    return _sort(rows, METRICS["cost_per_report"].dims)


@metric("lead_sources", "Lead source and conversion", dims=("country", "lead_source"),
        values=("orders_placed", "orders_paid", "conversion_pct"), base="orders_placed", uses=("line", "tier"),
        source="Orders (FR-ORD-005)",
        description="Orders placed in the period by the source the client gave, and the share paid. Leads who "
                    "never order are not recorded on the platform (issue I-07).")
def lead_sources(f: Filters) -> list[dict]:
    from orders.models import Order

    qs = _window(Order.objects.exclude(status="draft"), f, "created_at")
    if f.line:
        qs = qs.filter(kind__in=_kinds_for_line(f.line))
    if f.tier:
        qs = qs.filter(tier=f.tier)
    rows = []
    for r in qs.values("country__code", "lead_source").annotate(
            placed=Count("id"), paid=Count("id", filter=Q(status__in=["paid", "refunded"]))):
        rows.append({"country": r["country__code"], "lead_source": r["lead_source"] or "not_given",
                     "orders_placed": r["placed"], "orders_paid": r["paid"],
                     "conversion_pct": pct(r["paid"], r["placed"])})
    return _sort(rows, METRICS["lead_sources"].dims)


# --------------------------------------------------------------------------- family payments

PAID_FEE_STATUSES = ["paid", "receipted", "receipt_overdue"]


def paid_family_payments(f: Filters):
    from fees.models import Payment

    return _window(Payment.objects.filter(status__in=PAID_FEE_STATUSES), f, "paid_at")


@metric("family_payments", "Family payments to institutions", dims=("month", "country", "route", "currency"),
        values=("payments", "value", "with_receipt", "receipt_in_target", "receipt_in_target_pct",
                "receipt_overdue"), base="payments", line="family", source="Institution payments (FEE)",
        description="Payments made to verified schools, hospitals and providers, and the share with the "
                    "official receipt returned within the target days.")
def family_payments(f: Filters) -> list[dict]:
    has_receipt = Q(receipt_received_at__isnull=False) | Q(status="receipted")
    qs = (paid_family_payments(f).annotate(m=TruncMonth("paid_at")).values("m", "country__code", "route", "currency")
          .annotate(payments=Count("id"), value=Sum("amount"), with_receipt=Count("id", filter=has_receipt),
                    receipt_in_target=Count("id", filter=Q(receipt_received_at__isnull=False,
                                                           receipt_received_at__lte=F("receipt_due_at"))),
                    receipt_overdue=Count("id", filter=Q(status="receipt_overdue"))))
    rows = []
    for r in qs:
        rows.append({"month": _month(r["m"]), "country": r["country__code"], "route": r["route"],
                     "currency": r["currency"], "payments": r["payments"], "value": money(r["value"] or 0),
                     "with_receipt": r["with_receipt"], "receipt_in_target": r["receipt_in_target"],
                     "receipt_in_target_pct": pct(r["receipt_in_target"], r["payments"]),
                     "receipt_overdue": r["receipt_overdue"]})
    return _sort(rows, METRICS["family_payments"].dims)


# --------------------------------------------------------------------------- clients and transactions

def transactions(f: Filters) -> list[dict]:
    """Every transaction in the period: a paid order, a family payment made to an institution, or an escrow the
    bank confirmed as funded. One client paying for several services counts each one."""
    from escrow.models import Escrow
    from orders.models import Order

    out = []
    for client, code, at, kind in _window(Order.objects.filter(status="paid"), f, "paid_at") \
            .values_list("client_id", "country__code", "paid_at", "kind"):
        out.append({"client": client, "country": code, "at": at, "line": order_line(kind), "source": "order"})
    for client, code, at in paid_family_payments(f).values_list("invoice__client_id", "country__code", "paid_at"):
        out.append({"client": client, "country": code, "at": at, "line": "family", "source": "family_payment"})
    for client, code, at, kind in _window(Escrow.objects.filter(funded_at__isnull=False), f, "funded_at") \
            .values_list("client_id", "country__code", "funded_at", "kind"):
        out.append({"client": client, "country": code, "at": at, "line": ESCROW_LINE.get(kind, ""),
                    "source": "escrow"})
    if f.line:
        out = [t for t in out if t["line"] == f.line]
    return out


def _residence(client_ids) -> dict:
    from accounts.models import Person

    return dict(Person.objects.filter(pk__in=set(client_ids)).values_list("pk", "residence_country"))


def client_summary(f: Filters) -> dict:
    """{country: {active, repeat, diaspora, transactions}} for the whole period."""
    txs = transactions(f)
    res = _residence(t["client"] for t in txs)
    per = defaultdict(lambda: defaultdict(int))
    for t in txs:
        per[t["country"]][t["client"]] += 1
    out = {}
    for code, counts in per.items():
        active = len(counts)
        repeat = sum(1 for n in counts.values() if n >= 2)
        diaspora = sum(1 for c in counts if res.get(c) and res.get(c).upper() != code)
        out[code] = {"active": active, "repeat": repeat, "diaspora": diaspora, "transactions": sum(counts.values())}
    return out


@metric("clients", "Active and repeat clients", dims=("month", "country"),
        values=("active_clients", "repeat_clients", "repeat_share_pct", "diaspora_clients", "transactions"),
        base="active_clients", uses=("line",), source="Orders, family payments and escrows",
        description="Active: at least one transaction. Repeat: two or more. Diaspora: lives outside the country. "
                    "Month 'all' is the whole period.")
def clients(f: Filters) -> list[dict]:
    txs = transactions(f)
    res = _residence(t["client"] for t in txs)
    groups = defaultdict(lambda: defaultdict(int))
    for t in txs:
        groups[(_month(t["at"]), t["country"])][t["client"]] += 1
        groups[("all", t["country"])][t["client"]] += 1
    rows = []
    for (month, code), counts in groups.items():
        active = len(counts)
        repeat = sum(1 for n in counts.values() if n >= 2)
        rows.append({"month": month, "country": code, "active_clients": active, "repeat_clients": repeat,
                     "repeat_share_pct": pct(repeat, active),
                     "diaspora_clients": sum(1 for c in counts if res.get(c) and res[c].upper() != code),
                     "transactions": sum(counts.values())})
    return _sort(rows, METRICS["clients"].dims)


@metric("transactions_by_line", "Transactions per line", dims=("month", "country", "line", "source"),
        values=("transactions", "clients"), base="transactions", uses=("line",),
        source="Orders, family payments and escrows",
        description="Paid orders, family payments and funded escrows by product family.")
def transactions_by_line(f: Filters) -> list[dict]:
    groups = defaultdict(list)
    for t in transactions(f):
        groups[(_month(t["at"]), t["country"], t["line"], t["source"])].append(t["client"])
    rows = [{"month": m, "country": c, "line": ln, "source": s, "transactions": len(xs), "clients": len(set(xs))}
            for (m, c, ln, s), xs in groups.items()]
    return _sort(rows, METRICS["transactions_by_line"].dims)


# --------------------------------------------------------------------------- escrow and releases

def confirmed_releases(f: Filters):
    from escrow.models import ReleaseInstruction

    qs = _window(ReleaseInstruction.objects.filter(
        status="confirmed", kind__in=["release", "partial_release"], bank_confirmation_event__isnull=False),
        f, "bank_confirmation_event__occurred_at")
    if f.line:
        qs = qs.filter(escrow__kind__in=[k for k, ln in ESCROW_LINE.items() if ln == f.line])
    return qs


@metric("releases", "Releases confirmed by the bank", dims=("month", "country", "escrow_kind", "currency"),
        values=("releases", "value"), base="releases", uses=("line",), source="Escrow tracker (bank confirmations)",
        description="Release instructions the bank confirmed as paid, by the month of the bank's confirmation.")
def releases(f: Filters) -> list[dict]:
    qs = (confirmed_releases(f).annotate(m=TruncMonth("bank_confirmation_event__occurred_at"))
          .values("m", "country__code", "escrow__kind", "currency")
          .annotate(releases=Count("id"), value=Sum("amount")))
    rows = _rows(qs, {"month": "m", "country": "country__code", "escrow_kind": "escrow__kind",
                      "currency": "currency"}, {"releases": None, "value": lambda v: money(v or 0)})
    return _sort(rows, METRICS["releases"].dims)


@metric("release_clock", "Release clock (NFR-PERF-06)", dims=("month", "country"),
        values=("releases", "median_working_days", "p90_working_days", "target_working_days", "within_target",
                "sent_on_time_pct"), base="releases", line="property", source="Escrow release instructions",
        description="Purchase escrows: working days from the release clock's start to the bank's confirmation, "
                    "against release_median_target_working_days (an assumption), and the share sent by the "
                    "send-due day.")
def release_clock(f: Filters) -> list[dict]:
    from administration.selectors import setting

    cs = _Countries()
    groups = defaultdict(list)
    for code, started, confirmed, sent_at, due_on in confirmed_releases(f).filter(
            escrow__kind="purchase", clock_started_at__isnull=False).values_list(
            "country__code", "clock_started_at", "bank_confirmation_event__occurred_at", "sent_at", "send_due_on"):
        on_time = None if (sent_at is None or due_on is None) else cs.local_date(code, sent_at) <= due_on
        groups[(_month(confirmed), code)].append((cs.working_days(code, started, confirmed), on_time))
    rows = []
    for (month, code), xs in groups.items():
        target = setting("release_median_target_working_days", code, None)
        med = percentile([x[0] for x in xs], 0.5)
        timed = [x[1] for x in xs if x[1] is not None]
        rows.append({"month": month, "country": code, "releases": len(xs), "median_working_days": med,
                     "p90_working_days": percentile([x[0] for x in xs], 0.9),
                     "target_working_days": target,
                     "within_target": None if target in (None, "") else med <= float(target),
                     "sent_on_time_pct": pct(sum(1 for t in timed if t), len(timed))})
    return _sort(rows, METRICS["release_clock"].dims)


@metric("escrows", "Escrows opened", dims=("month", "country", "kind", "currency"),
        values=("opened", "agreed_value", "funded", "cancelled"), base="opened", uses=("line",),
        source="Escrow tracker",
        description="Escrows opened in the month, the agreed value from the terms, and how many the bank has "
                    "since confirmed as funded or that were cancelled.")
def escrows(f: Filters) -> list[dict]:
    from escrow.models import Escrow

    qs = _window(Escrow.objects.all(), f, "created_at")
    if f.line:
        qs = qs.filter(kind__in=[k for k, ln in ESCROW_LINE.items() if ln == f.line])
    qs = (qs.annotate(m=TruncMonth("created_at")).values("m", "country__code", "kind", "currency")
          .annotate(opened=Count("id"), agreed_value=Sum("agreed_amount"),
                    funded=Count("id", filter=Q(funded_at__isnull=False)),
                    cancelled=Count("id", filter=Q(status="cancelled"))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "kind": "kind", "currency": "currency"},
                 {"opened": None, "agreed_value": lambda v: money(v or 0), "funded": None, "cancelled": None})
    return _sort(rows, METRICS["escrows"].dims)


@metric("held_at_bank", "Value held at the bank", dims=("country", "escrow_kind", "currency"),
        values=("escrows", "held_at_bank", "released_in_period"), base="escrows", uses=("line",),
        source="Bank confirmations (esc_bank_event)",
        description="Bank-confirmed money in less bank-confirmed money out at the end of the period, and the "
                    "releases confirmed in the period. Tenmina never holds this money.")
def held_at_bank(f: Filters) -> list[dict]:
    from escrow.models import BankEvent
    from escrow.selectors import IN_KINDS, OUT_KINDS

    qs = BankEvent.objects.filter(status="confirmed", occurred_at__lt=f.end)
    if f.countries is not None:
        qs = qs.filter(country__code__in=f.countries)
    if f.line:
        qs = qs.filter(escrow__kind__in=[k for k, ln in ESCROW_LINE.items() if ln == f.line])
    in_period = Q(kind="release_confirmed", occurred_at__gte=f.start)
    rows = []
    for r in qs.values("country__code", "escrow__kind", "currency").annotate(
            escrows=Count("escrow_id", distinct=True), ins=Sum("amount", filter=Q(kind__in=IN_KINDS)),
            outs=Sum("amount", filter=Q(kind__in=OUT_KINDS)), released=Sum("amount", filter=in_period)):
        rows.append({"country": r["country__code"], "escrow_kind": r["escrow__kind"], "currency": r["currency"],
                     "escrows": r["escrows"], "held_at_bank": money((r["ins"] or 0) - (r["outs"] or 0)),
                     "released_in_period": money(r["released"] or 0)})
    return _sort(rows, METRICS["held_at_bank"].dims)


# --------------------------------------------------------------------------- disputes, payment runs, field work

@metric("disputes", "Disputes", dims=("month", "country", "category"),
        values=("opened", "resolved", "resolved_within_timeline", "open_now"), base="opened", source="Disputes",
        description="Disputes opened in the month; resolved means closed or withdrawn; within the timeline means "
                    "closed by the decision due date.")
def disputes(f: Filters) -> list[dict]:
    from disputes.models import OPEN_STATUSES, Dispute

    qs = (_window(Dispute.objects.all(), f, "created_at").annotate(m=TruncMonth("created_at"))
          .values("m", "country__code", "category")
          .annotate(opened=Count("id"), resolved=Count("id", filter=Q(status__in=["closed", "withdrawn"])),
                    resolved_within_timeline=Count("id", filter=Q(status="closed", decision_due__isnull=False,
                                                                  closed_at__date__lte=F("decision_due"))),
                    open_now=Count("id", filter=Q(status__in=OPEN_STATUSES))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "category": "category"},
                 {"opened": None, "resolved": None, "resolved_within_timeline": None, "open_now": None})
    return _sort(rows, METRICS["disputes"].dims)


@metric("payment_runs", "Professional payment runs", dims=("month", "country", "currency", "status"),
        values=("runs", "lines", "total_net"), base="runs", source="Professional payments (PRO)",
        description="Payment runs from Tenmina's operating account to lawyers, surveyors, runners and other "
                    "professionals, by the month prepared.")
def payment_runs(f: Filters) -> list[dict]:
    from profpay.models import PaymentRun

    qs = (_window(PaymentRun.objects.all(), f, "created_at").annotate(m=TruncMonth("created_at"))
          .values("m", "country__code", "currency", "status")
          .annotate(runs=Count("id"), lines=Sum("line_count"), total_net=Sum("total_net")))
    rows = _rows(qs, {"month": "m", "country": "country__code", "currency": "currency", "status": "status"},
                 {"runs": None, "lines": None, "total_net": lambda v: money(v or 0)})
    return _sort(rows, METRICS["payment_runs"].dims)


@metric("field_submissions", "Field evidence and inspections", dims=("month", "country", "subject_type", "kind"),
        values=("submissions", "held_for_review", "passed", "passed_with_defects", "failed"), base="submissions",
        source="Tenmina Field (MOB)", description="Evidence sets and inspection results received from the field app.")
def field_submissions(f: Filters) -> list[dict]:
    from mobile.models import Submission

    qs = (_window(Submission.objects.all(), f, "received_at").annotate(m=TruncMonth("received_at"))
          .values("m", "country__code", "subject_type", "kind")
          .annotate(submissions=Count("id"), held_for_review=Count("id", filter=Q(status="held_for_review")),
                    passed=Count("id", filter=Q(outcome="pass")),
                    passed_with_defects=Count("id", filter=Q(outcome="pass_with_defects")),
                    failed=Count("id", filter=Q(outcome="fail"))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "subject_type": "subject_type", "kind": "kind"},
                 {"submissions": None, "held_for_review": None, "passed": None, "passed_with_defects": None,
                  "failed": None})
    return _sort(rows, METRICS["field_submissions"].dims)


@metric("field_flags", "Field evidence flags", dims=("month", "country", "kind"),
        values=("flags", "open", "cleared", "upheld"), base="flags", source="Tenmina Field server checks (8.7)",
        description="Signature, location and device checks that held evidence for a reviewer.")
def field_flags(f: Filters) -> list[dict]:
    from mobile.models import FraudFlag

    qs = (_window(FraudFlag.objects.all(), f, "created_at").annotate(m=TruncMonth("created_at"))
          .values("m", "country__code", "kind")
          .annotate(flags=Count("id"), open=Count("id", filter=Q(status="open")),
                    cleared=Count("id", filter=Q(status="cleared")), upheld=Count("id", filter=Q(status="upheld"))))
    rows = _rows(qs, {"month": "m", "country": "country__code", "kind": "kind"},
                 {"flags": None, "open": None, "cleared": None, "upheld": None})
    return _sort(rows, METRICS["field_flags"].dims)


@metric("milestones", "Building milestones", dims=("month", "country"),
        values=("submitted", "inspected", "passed_first_time", "failed", "flagged"), base="submitted",
        line="property", source="Construction (BLD) and Tenmina Field",
        description="Milestones submitted by contractors, milestone inspections recorded, milestones whose first "
                    "inspection passed, failed inspections and field flags on milestones.")
def milestones(f: Filters) -> list[dict]:
    from construction.models import Inspection, Milestone
    from mobile.models import FraudFlag

    rows = defaultdict(lambda: {"submitted": 0, "inspected": 0, "passed_first_time": 0, "failed": 0, "flagged": 0})
    for code, at in _window(Milestone.objects.filter(submitted_at__isnull=False), f, "submitted_at") \
            .values_list("country__code", "submitted_at"):
        rows[(_month(at), code)]["submitted"] += 1
    first_seen = set()
    for mid, code, at, outcome in Inspection.objects.filter(
            kind="milestone", status="recorded", milestone__isnull=False, recorded_at__isnull=False,
            recorded_at__lt=f.end).order_by("milestone_id", "recorded_at").values_list(
            "milestone_id", "country__code", "recorded_at", "outcome"):
        first = mid not in first_seen
        first_seen.add(mid)
        if at < f.start or (f.countries is not None and code not in f.countries):
            continue
        r = rows[(_month(at), code)]
        r["inspected"] += 1
        r["failed"] += outcome == "fail"
        r["passed_first_time"] += first and outcome in ("pass", "pass_with_defects")
    for code, at in _window(FraudFlag.objects.filter(subject_type="milestone"), f, "created_at") \
            .values_list("country__code", "created_at"):
        rows[(_month(at), code)]["flagged"] += 1
    out = [{"month": m, "country": c, **{k: int(v) for k, v in vals.items()}} for (m, c), vals in rows.items()]
    return _sort(out, METRICS["milestones"].dims)


# --------------------------------------------------------------------------- other lines (counts only)

@metric("listings", "Listings", dims=("month", "country"), values=("created", "went_live", "enquiries", "sold"),
        base=None, line="property", source="Listings (LST)",
        description="Listings created, put live, enquiries received and plots sold through escrow.")
def listings(f: Filters) -> list[dict]:
    from listings.models import Enquiry, Listing

    rows = defaultdict(lambda: {"created": 0, "went_live": 0, "enquiries": 0, "sold": 0})
    for col, qs, at in (("created", Listing.objects.all(), "created_at"),
                        ("went_live", Listing.objects.filter(live_at__isnull=False), "live_at"),
                        ("enquiries", Enquiry.objects.all(), "created_at"),
                        ("sold", Listing.objects.filter(sold_at__isnull=False), "sold_at")):
        for r in _window(qs, f, at).annotate(m=TruncMonth(at)).values("m", "country__code").annotate(n=Count("id")):
            rows[(_month(r["m"]), r["country__code"])][col] += r["n"]
    out = [{"month": m, "country": c, **v} for (m, c), v in rows.items()]
    return _sort(out, METRICS["listings"].dims)


@metric("care_visits", "Care visits", dims=("month", "country"),
        values=("scheduled", "completed", "confirmed_by_family", "missed"), base="scheduled", line="family",
        source="Care visits (CARE), statuses only",
        description="Visits by the month of their window. Readings and concerns are never read (TR-12).")
def care_visits(f: Filters) -> list[dict]:
    from care.models import Visit

    qs = (_window(Visit.objects.all(), f, "window_start").annotate(m=TruncMonth("window_start"))
          .values("m", "country__code")
          .annotate(scheduled=Count("id"),
                    completed=Count("id", filter=Q(status__in=["checked_out", "confirmed", "unconfirmed"])),
                    confirmed_by_family=Count("id", filter=Q(status="confirmed")),
                    missed=Count("id", filter=Q(status="missed"))))
    rows = _rows(qs, {"month": "m", "country": "country__code"},
                 {"scheduled": None, "completed": None, "confirmed_by_family": None, "missed": None})
    return _sort(rows, METRICS["care_visits"].dims)


@metric("property_management", "Property management", dims=("month", "country", "currency"),
        values=("properties_taken_on", "rent_periods_received", "rent_received", "repairs_completed"), base=None,
        line="property", source="Property management (PMG)",
        description="Properties taken on, rent the owner's bank statement shows as received, repairs finished.")
def property_management(f: Filters) -> list[dict]:
    from propertymgmt.models import ManagedProperty, RentPeriod, Repair

    rows = defaultdict(lambda: {"properties_taken_on": 0, "rent_periods_received": 0, "rent_received": Decimal("0"),
                                "repairs_completed": 0})
    for r in _window(ManagedProperty.objects.filter(managed_at__isnull=False), f, "managed_at") \
            .annotate(m=TruncMonth("managed_at")).values("m", "country__code").annotate(n=Count("id")):
        rows[(_month(r["m"]), r["country__code"], "")]["properties_taken_on"] += r["n"]
    for code, on, cur, amount in _date_window(RentPeriod.objects.filter(received_on__isnull=False), f, "received_on",
                                              country="tenancy__country") \
            .values_list("tenancy__country__code", "received_on", "expected_currency", "received_amount"):
        r = rows[(_month(on), code, cur)]
        r["rent_periods_received"] += 1
        r["rent_received"] += amount or 0
    for r in _window(Repair.objects.filter(work_done_at__isnull=False), f, "work_done_at") \
            .annotate(m=TruncMonth("work_done_at")).values("m", "country__code").annotate(n=Count("id")):
        rows[(_month(r["m"]), r["country__code"], "")]["repairs_completed"] += r["n"]
    out = [{"month": m, "country": c, "currency": cur, **v, "rent_received": money(v["rent_received"])}
           for (m, c, cur), v in rows.items()]
    return _sort(out, METRICS["property_management"].dims)


@metric("errands", "Errands", dims=("month", "country"), values=("completed", "median_days"), base="completed",
        line="projects", source="Errands (TSK)",
        description="Errands completed in the month and the median calendar days from order to completion.")
def errands(f: Filters) -> list[dict]:
    from errands.models import Errand

    groups = defaultdict(list)
    for code, created, done in _window(Errand.objects.filter(completed_at__isnull=False), f, "completed_at") \
            .values_list("country__code", "created_at", "completed_at"):
        groups[(_month(done), code)].append((done - created).total_seconds() / 86400.0)
    rows = [{"month": m, "country": c, "completed": len(xs), "median_days": percentile(xs, 0.5)}
            for (m, c), xs in groups.items()]
    return _sort(rows, METRICS["errands"].dims)


@metric("insurance", "Insurer partner cover", dims=("month", "country"), values=("policies_sold", "claims_paid"),
        base=None, line="family", source="Insurer lines (INS), statuses only",
        description="Policies the licensed insurer issued through Tenmina and claims the insurer reports as paid. "
                    "Applications are never read (TR-12).")
def insurance(f: Filters) -> list[dict]:
    from insurance.models import Claim, Policy

    rows = defaultdict(lambda: {"policies_sold": 0, "claims_paid": 0})
    for r in _window(Policy.objects.all(), f, "created_at").annotate(m=TruncMonth("created_at")) \
            .values("m", "country__code").annotate(n=Count("id")):
        rows[(_month(r["m"]), r["country__code"])]["policies_sold"] += r["n"]
    for r in _window(Claim.objects.filter(insurer_status="paid", insurer_status_at__isnull=False), f,
                     "insurer_status_at").annotate(m=TruncMonth("insurer_status_at")) \
            .values("m", "country__code").annotate(n=Count("id")):
        rows[(_month(r["m"]), r["country__code"])]["claims_paid"] += r["n"]
    out = [{"month": m, "country": c, **v} for (m, c), v in rows.items()]
    return _sort(out, METRICS["insurance"].dims)


# --------------------------------------------------------------------------- the day-90 review

# docs/validation-plan.md section 6, "Go to phase 2". Working assumptions, changeable per country
# in the published configuration under analytics.day90_targets.
DAY90_TARGETS = {
    "property_reports_delivered": (">=", 20),
    "family_payments_with_receipt": (">=", 60),
    "active_clients": (">=", 40),
    "repeat_share_pct": (">=", 30),
    "diaspora_clients": (">=", 12),
    "median_turnaround_working_days": ("<", 25),
    "cost_share_pct": ("<", 50),
    "green_report_clients_to_escrow_pct": (">=", 30),
}


def _target(code, measure):
    from countries.selectors import config

    op, default = DAY90_TARGETS[measure]
    override = None
    try:
        override = (config(code, "analytics.day90_targets", {}) or {}).get(measure)
    except Exception:  # noqa: BLE001 - an unknown country has no configuration
        override = None
    return op, (override if override is not None else default)


@metric("day90_review", "Day-90 review", dims=("country", "measure"),
        values=("value", "n", "comparison", "target", "status"), base=None, source="All modules",
        description="The go criteria of the validation plan, measured from platform data for the period. Targets "
                    "are working assumptions. Escrow asks are measured as escrows opened by clients with a green "
                    "report; a spoken ask is not recorded on the platform.")
def day90_review(f: Filters) -> list[dict]:
    from escrow.models import Escrow

    plain = Filters(f.date_from, f.date_to, f.countries)
    delivered = defaultdict(int)
    for r in released_reports(plain).exclude(case__order__kind="listing_verification") \
            .values("country__code").annotate(n=Count("id")):
        delivered[r["country__code"]] = r["n"]
    receipts = defaultdict(int)
    for r in paid_family_payments(plain).filter(Q(receipt_received_at__isnull=False) | Q(status="receipted")) \
            .values("country__code").annotate(n=Count("id")):
        receipts[r["country__code"]] = r["n"]
    summary = client_summary(plain)
    tat = defaultdict(list)
    for code, _m, _ln, wd, _cd in turnaround_samples(plain):
        tat[code].append(wd)
    cost = defaultdict(lambda: [Decimal("0"), Decimal("0"), 0])
    for s in cost_samples(plain):
        if s["price"]:
            c = cost[s["country"]]
            c[0] += s["cost"]
            c[1] += s["price"]
            c[2] += 1
    green = defaultdict(set)
    for code, client in released_reports(plain).filter(overall_verdict="green", case__client__isnull=False) \
            .values_list("country__code", "case__client_id"):
        green[code].add(client)
    escrow_clients = defaultdict(set)
    for code, client in Escrow.objects.filter(client_id__in={c for s in green.values() for c in s},
                                              created_at__lt=plain.end).values_list("country__code", "client_id"):
        escrow_clients[code].add(client)
    codes = set(delivered) | set(receipts) | set(summary) | set(tat) | set(cost) | set(green)
    if f.countries is not None:
        codes |= set(f.countries)
    rows = []
    for code in sorted(codes):
        s = summary.get(code, {"active": 0, "repeat": 0, "diaspora": 0})
        c = cost.get(code)
        measures = {
            "property_reports_delivered": (delivered.get(code, 0), delivered.get(code, 0)),
            "family_payments_with_receipt": (receipts.get(code, 0), receipts.get(code, 0)),
            "active_clients": (s["active"], s["active"]),
            "repeat_share_pct": (pct(s["repeat"], s["active"]), s["active"]),
            "diaspora_clients": (s["diaspora"], s["active"]),
            "median_turnaround_working_days": (percentile(tat.get(code, []), 0.5), len(tat.get(code, []))),
            "cost_share_pct": (pct(c[0], c[1]) if c else None, c[2] if c else 0),
            "green_report_clients_to_escrow_pct": (pct(len(green[code] & escrow_clients[code]), len(green[code])),
                                                   len(green[code])),
        }
        for measure, (value, n) in measures.items():
            op, target = _target(code, measure)
            if value is None:
                status = "no_data"
            else:
                status = "met" if (value >= target if op == ">=" else value < target) else "not_met"
            rows.append({"country": code, "measure": measure, "value": value, "n": n, "comparison": op,
                         "target": target, "status": status})
    return rows


# --------------------------------------------------------------------------- small-number suppression (FR-ANL-003)

DEFAULT_MIN_GROUP = 5  # [TO VERIFY] TC-ANL-003-02


def min_group_size(codes) -> int:
    """The largest minimum group size configured for the countries in view."""
    from countries.selectors import config

    sizes = []
    for code in codes or []:
        try:
            sizes.append(int(config(code, "analytics.min_group_size", DEFAULT_MIN_GROUP)))
        except Exception:  # noqa: BLE001
            sizes.append(DEFAULT_MIN_GROUP)
    return max(sizes) if sizes else DEFAULT_MIN_GROUP


def suppress(m: Metric, rows: list[dict], k: int) -> tuple[list[dict], int]:
    """Blank every value in a row whose group is smaller than k (but not empty), so that a narrow filter cannot
    single out one client. Returns the rows and the number of cells blanked."""
    blanked = 0
    out = []
    for r in rows:
        r = dict(r)
        if m.name == "day90_review":
            small = isinstance(r.get("n"), int) and 0 < r["n"] < k
            if small:
                r["value"], r["status"] = None, "suppressed"
                blanked += 1
        elif m.base:
            n = r.get(m.base)
            if isinstance(n, int) and 0 < n < k:
                for col in m.values:
                    if r.get(col) not in (None, ""):
                        blanked += 1
                    r[col] = None
                r["suppressed"] = True
        else:
            for col in m.values:
                v = r.get(col)
                if isinstance(v, int) and not isinstance(v, bool) and 0 < v < k:
                    r[col] = None
                    blanked += 1
        out.append(r)
    return out, blanked


__all__ = ["Filters", "METRICS", "Metric", "suppress", "min_group_size"]
