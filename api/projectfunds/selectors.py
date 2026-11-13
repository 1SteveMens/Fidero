"""PRJ Project funds: read-only queries other modules may use.

- suppliers_of(project), invoices_of(project), checks_of(project)
- checked_suppliers(project)      suppliers money may go to (RUL-21)
"""
from .models import AmlReview, BackgroundCheck, Invoice, Supplier


def suppliers_of(project):
    return Supplier.objects.filter(project=project).exclude(status="removed").order_by("created_at")


def checked_suppliers(project):
    return suppliers_of(project).filter(status="passed", payee__verification_status="verified")


def invoices_of(project):
    return Invoice.objects.filter(project=project).order_by("-created_at")


def checks_of(project):
    return BackgroundCheck.objects.filter(project=project).order_by("created_at")


def aml_review(project):
    return AmlReview.objects.filter(project=project).first()
