"""PMG background jobs (02 section 7.12). The beat schedule should add propertymgmt.match_rent daily at
07:00 GMT and propertymgmt.schedule_inspections monthly. Statement lines are also matched on import."""
from celery import shared_task

from . import services


@shared_task(name="propertymgmt.match_rent")
def match_rent():
    return services.rent_watch()


@shared_task(name="propertymgmt.schedule_inspections")
def schedule_inspections():
    return services.scheduled_inspection_watch()
