"""Hooks other modules register with DPR, so DPR never imports them.

- open_matters: fn(person) -> [{"kind", "id", "title", "reason"}]. Open money
  matters (an open escrow, money held at the bank, a standing approval) that
  delay an account deletion (FR-APP-004, issue I-30).
- exporters: fn(person) -> dict. A person's data for a subject access export
  (FR-DPR-003). Only that person's own data; third parties redacted.
- retention finders: fn(scope, cutoff) -> iterable of Candidate for one data
  class (FR-DPR-004). `scope.country` is a Country or None; when None, skip
  rows whose country is in `scope.exclude` (they have their own rule).

    from dataprotection import registry

    @registry.open_matters
    def open_escrows(person): ...

    @registry.exporter("escrow")
    def export_escrows(person): ...

    @registry.retention("case")
    def expired_cases(scope, cutoff): yield registry.Candidate("case", c.pk, apply=lambda: ..., related=[...])
"""
from dataclasses import dataclass, field
from typing import Callable

_open_matters: list = []
_exporters: dict = {}
_finders: dict = {}


@dataclass
class Candidate:
    subject_type: str
    subject_id: object
    apply: Callable
    related: list = field(default_factory=list)  # [(subject_type, subject_id)] whose hold also protects this
    label: str = ""


@dataclass
class Scope:
    country: object = None
    exclude: list = field(default_factory=list)

    def filter(self, qs, country_field="country"):
        if self.country is not None:
            return qs.filter(**{country_field: self.country})
        if self.exclude:
            return qs.exclude(**{f"{country_field}__in": self.exclude})
        return qs


def open_matters(fn):
    if fn not in _open_matters:
        _open_matters.append(fn)
    return fn


def exporter(name):
    def deco(fn):
        _exporters[name] = fn
        return fn

    return deco


def retention(data_class):
    def deco(fn):
        _finders.setdefault(data_class, [])
        if fn not in _finders[data_class]:
            _finders[data_class].append(fn)
        return fn

    return deco


def collect_open_matters(person) -> list[dict]:
    out = []
    for fn in list(_open_matters):
        out.extend(fn(person) or [])
    return out


def collect_export(person) -> dict:
    return {name: fn(person) for name, fn in sorted(_exporters.items())}


def finders(data_class):
    return list(_finders.get(data_class, []))
