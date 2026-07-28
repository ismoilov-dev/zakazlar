from django.db import migrations


def update_external_order_ids(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    for sale in Sale.objects.all():
        if sale.ordered_at and sale.external_order_id:
            month_prefix = sale.ordered_at.strftime("%Y%m")
            if not sale.external_order_id.startswith(f"{month_prefix}_"):
                sale.external_order_id = f"{month_prefix}_{sale.external_order_id}"
                sale.save(update_fields=["external_order_id"])


def reverse_external_order_ids(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0004_alter_sale_import_job"),
    ]

    operations = [
        migrations.RunPython(update_external_order_ids, reverse_external_order_ids),
    ]
