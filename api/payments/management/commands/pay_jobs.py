"""Scheduled PAY jobs (02 section 7.12; IF-02 fallback).

    python manage.py pay_jobs pending            # every 15 minutes: verify open attempts, time out the rest
    python manage.py pay_jobs settlement [DATE]  # daily: reconcile yesterday's (or DATE's) settlement
"""
from datetime import date

from django.core.management.base import BaseCommand

from payments import services


class Command(BaseCommand):
    help = "Run a PAY job: pending or settlement."

    def add_arguments(self, parser):
        parser.add_argument("job", choices=["pending", "settlement"])
        parser.add_argument("date", nargs="?", help="Settlement date, YYYY-MM-DD")

    def handle(self, *args, job, date=None, **opts):
        if job == "pending":
            self.stdout.write(str(services.reconcile_pending()))
        else:
            d = _date(date) if date else None
            for run in services.daily_reconcile(d):
                self.stdout.write(f"{run.country.code} {run.settlement_date}: {run.line_count} lines, "
                                  f"{run.matched} matched, {run.issues} issues")


def _date(s):
    return date.fromisoformat(s)
