"""ACC background jobs (02 section 7.12). The beat schedule in settings
should add: accounts.licence_expiry daily, accounts.national_id_retry every
15 minutes, accounts.vetting_expiry and accounts.invitation_expiry daily."""
from celery import shared_task

from . import services


@shared_task(name="accounts.licence_expiry")
def licence_expiry():
    return services.expire_licences()


@shared_task(name="accounts.national_id_retry")
def national_id_retry():
    return services.retry_national_id_checks()


@shared_task(name="accounts.vetting_expiry")
def vetting_expiry():
    return services.expire_vettings()


@shared_task(name="accounts.invitation_expiry")
def invitation_expiry():
    return services.expire_invitations()
