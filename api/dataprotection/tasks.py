"""DPR background jobs (02 section 7.12). The beat schedule should add
dataprotection.retention_sweep nightly and the others daily."""
from celery import shared_task

from . import services


@shared_task(name="dataprotection.retention_sweep")
def retention_sweep():
    return str(services.run_retention().pk)


@shared_task(name="dataprotection.process_waiting_deletions")
def process_waiting_deletions():
    return services.process_waiting_deletions()


@shared_task(name="dataprotection.bulk_export_expiry")
def bulk_export_expiry():
    return services.expire_bulk_exports()


@shared_task(name="dataprotection.overdue_requests")
def overdue_requests():
    return services.alert_overdue_requests()
