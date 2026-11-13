"""CASE background jobs (02 section 7.12). The beat schedule should add cases.task_overdue daily and
cases.search_result_watch daily."""
from celery import shared_task

from . import services


@shared_task(name="cases.task_overdue")
def task_overdue():
    return services.mark_overdue()


@shared_task(name="cases.search_result_watch")
def search_result_watch():
    return services.search_result_watch()


@shared_task(name="cases.create_from_order")
def create_from_order(order_id):
    case = services.create_from_order(order_id)
    return str(case.pk) if case else None
