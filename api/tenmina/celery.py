"""Celery app (ADR-08). Tasks live in each module's tasks.py.

In development and tests CELERY_TASK_ALWAYS_EAGER runs tasks inline.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tenmina.settings")
app = Celery("tenmina")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
