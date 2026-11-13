"""CTY jobs (02 section 7.12): countries.copy_config on demand."""
from celery import shared_task


@shared_task(name="countries.copy_config")
def copy_config(source_config_id, target_country_id, by_id):
    from accounts.models import Person

    from .models import Country, CountryConfig
    from .services import copy_config as run

    cfg = run(CountryConfig.objects.get(pk=source_config_id), Country.objects.get(pk=target_country_id),
              by=Person.objects.get(pk=by_id))
    return str(cfg.pk)
