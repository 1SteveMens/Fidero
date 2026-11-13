"""pro_scope is seeded by migration only (02 6.14, RUL-26). Every key is fixed
before the work starts: the standard rate, the report tier, a plot size band
or a travel distance band. Bands are working assumptions [TO VERIFY]."""
from django.db import migrations

SCOPES = [
    ("standard", "The standard rate for the unit"),
    ("tier_basic", "Basic check tier, chosen when the client orders"),
    ("tier_standard", "Standard verification tier, chosen when the client orders"),
    ("tier_premium", "Premium verification tier with survey, chosen when the client orders"),
    ("plot_up_to_1_acre", "Plot of up to one acre on the order [TO VERIFY]"),
    ("plot_over_1_acre", "Plot of more than one acre on the order [TO VERIFY]"),
    ("travel_within_city", "Site within the city of the professional's base [TO VERIFY]"),
    ("travel_regional", "Site outside the city, within the region [TO VERIFY]"),
    ("travel_long_distance", "Site in another region [TO VERIFY]"),
]


def add(apps, schema_editor):
    Scope = apps.get_model("profpay", "Scope")
    # The trigger in profpay/dbsql.py refuses any write to pro_scope outside a migration.
    schema_editor.execute("SELECT set_config('tenmina.pro_scope_migration', 'on', true)")
    for key, description in SCOPES:
        Scope.objects.update_or_create(key=key, defaults={"description": description, "known_at": "assignment"})


class Migration(migrations.Migration):
    dependencies = [("profpay", "0001_initial")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
