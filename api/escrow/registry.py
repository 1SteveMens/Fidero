"""Hooks the line modules register with ESC, so ESC never imports them.

Subject checks: each line that pays through escrow registers what must be
true of its own subject before money moves (02 6.5 esc.release_blockers()):

    from escrow import registry

    @registry.subject_check("care_visit")
    def visit_confirmed(instruction) -> list[dict]:
        visit = Visit.objects.get(pk=instruction.subject_id)
        if visit.status != "confirmed":
            return [{"rule": "RUL-23", "code": "visit-not-confirmed",
                     "message": "The family has not confirmed this visit."}]
        return []

The check runs when the release is prepared, when the client and each staff
member approve, and again just before the instruction is sent.

Subject labels: `registry.subject_label("fee_invoice", fn)` where
fn(subject_id) -> str names the subject on statements and instructions.
"""
import logging

log = logging.getLogger("escrow")
_checks: dict = {}
_labels: dict = {}


def subject_check(subject_type):
    def deco(fn):
        _checks.setdefault(subject_type, [])
        if fn not in _checks[subject_type]:
            _checks[subject_type].append(fn)
        return fn

    return deco


def register_subject_check(subject_type, fn):
    return subject_check(subject_type)(fn)


def unregister_subject_check(subject_type, fn):
    if fn in _checks.get(subject_type, []):
        _checks[subject_type].remove(fn)


def subject_label(subject_type, fn):
    _labels[subject_type] = fn


def label_for(subject_type, subject_id) -> str:
    fn = _labels.get(subject_type)
    if fn is None:
        return ""
    try:
        return str(fn(subject_id) or "")
    except Exception:  # noqa: BLE001
        return ""


def run_checks(instruction) -> list[dict]:
    out = []
    for fn in _checks.get(instruction.subject_type or "", []):
        try:
            out.extend(fn(instruction) or [])
        except Exception as exc:  # noqa: BLE001 - a failing check blocks; it never lets money through
            log.exception("subject check %s failed", fn)
            out.append({"rule": "RUL-06", "code": "subject-check-failed",
                        "message": f"The {instruction.subject_type.replace('_', ' ')} could not be checked: {exc}"})
    return out
