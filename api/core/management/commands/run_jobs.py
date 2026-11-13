"""Run a scheduled background job once, now, in this process (development and support).

    python manage.py run_jobs --list
    python manage.py run_jobs fees.schedule_due
    python manage.py run_jobs escrow.release_clock_watch evidence.integrity_sample

The names are those in tenmina/celery_schedule.py. The job runs exactly as the
beat schedule would run it, with its own rules: nothing is approved or
released by running a job.
"""
import difflib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def scheduled_task(name):
    """The Celery task for a scheduled job name."""
    from tenmina.celery import app

    entry = settings.CELERY_BEAT_SCHEDULE.get(name)
    if entry is None:
        close = difflib.get_close_matches(name, list(settings.CELERY_BEAT_SCHEDULE), n=3)
        hint = f" Did you mean {', '.join(close)}?" if close else " Use --list to see them."
        raise CommandError(f"There is no scheduled job called {name}.{hint}")
    app.loader.import_default_modules()
    task = app.tasks.get(entry["task"])
    if task is None:
        raise CommandError(f"The job {name} is scheduled but no task {entry['task']} is registered.")
    return task


class Command(BaseCommand):
    help = "Run scheduled background jobs once by name (see tenmina/celery_schedule.py)."

    def add_arguments(self, parser):
        parser.add_argument("names", nargs="*", help="Job names, for example fees.schedule_due")
        parser.add_argument("--list", action="store_true", help="List the scheduled jobs and their schedules")

    def handle(self, *args, names, list=False, **opts):
        from tenmina.celery_schedule import JOBS

        if list or not names:
            for name, (schedule, what) in JOBS.items():
                self.stdout.write(f"{name:45} {schedule!s:60} {what}")
            if not names:
                return
        tasks = [(n, scheduled_task(n)) for n in names]
        for name, task in tasks:
            result = task.apply(throw=True).get()
            self.stdout.write(self.style.SUCCESS(f"{name}: {result}"))
