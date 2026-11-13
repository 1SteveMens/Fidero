"""Scheduled audit jobs (02 section 7.12). Add to the beat schedule:
audit.anchor_head hourly, audit.verify_chain daily."""
from celery import shared_task


@shared_task(name="audit.anchor_head")
def anchor_head():
    from .services import anchor

    a = anchor()
    return a.seq if a else None


@shared_task(name="audit.verify_chain")
def verify_chain():
    from .services import run_chain_check

    return run_chain_check().ok
