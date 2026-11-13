"""Run the evidence jobs by hand: `python manage.py evidence_jobs integrity --size 50` or
`python manage.py evidence_jobs retention`."""
from django.core.management.base import BaseCommand

from evidence import services


class Command(BaseCommand):
    help = "Evidence integrity sampling and retention sweep"

    def add_arguments(self, parser):
        parser.add_argument("job", choices=["integrity", "retention"])
        parser.add_argument("--size", type=int, default=None)
        parser.add_argument("--seed", default=None)

    def handle(self, *args, job, size, seed, **opts):
        if job == "integrity":
            run = services.integrity_sample(size=size, seed=seed)
            self.stdout.write(f"checked {run.checked} of {run.population}, mismatches {run.mismatches}")
        else:
            done = services.retention_sweep()
            self.stdout.write(f"deleted {len(done)} items past retention")
