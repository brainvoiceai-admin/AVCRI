# Generated migration: replace min_max with min_quantity and max_quantity

import re
from django.db import migrations, models


def parse_min_max(value):
    """Parse min_max string like '10/20', '10-20', '10,20' or single number into (min, max)."""
    if not value or not isinstance(value, str):
        return None, None
    s = value.strip()
    if not s:
        return None, None
    # Try patterns: 10/20, 10-20, 10,20, 10 20
    parts = re.split(r'[/,\-\s]+', s)
    parts = [p.strip() for p in parts if p.strip()]
    try:
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
        if len(parts) == 1:
            n = int(parts[0])
            return n, n
    except (ValueError, TypeError):
        pass
    return None, None


def migrate_min_max_to_separate(apps, schema_editor):
    ItemMaster = apps.get_model('masters', 'ItemMaster')
    for item in ItemMaster.objects.all():
        if hasattr(item, 'min_max') and item.min_max:
            min_qty, max_qty = parse_min_max(item.min_max)
            item.min_quantity = min_qty
            item.max_quantity = max_qty
            item.save()


def reverse_migrate(apps, schema_editor):
    """Restore min_max string from min_quantity/max_quantity when reversing (min_max re-added by RemoveField reverse)."""
    ItemMaster = apps.get_model('masters', 'ItemMaster')
    for item in ItemMaster.objects.all():
        if item.min_quantity is not None or item.max_quantity is not None:
            parts = []
            if item.min_quantity is not None:
                parts.append(str(item.min_quantity))
            if item.max_quantity is not None:
                parts.append(str(item.max_quantity))
            if hasattr(item, 'min_max'):
                item.min_max = '/'.join(parts) if parts else None
                item.save()


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0030_fix_umo_to_uom_verbose_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemmaster',
            name='min_quantity',
            field=models.IntegerField(blank=True, null=True, verbose_name='Min Quantity'),
        ),
        migrations.AddField(
            model_name='itemmaster',
            name='max_quantity',
            field=models.IntegerField(blank=True, null=True, verbose_name='Max Quantity'),
        ),
        migrations.RunPython(migrate_min_max_to_separate, reverse_migrate),
        migrations.RemoveField(
            model_name='itemmaster',
            name='min_max',
        ),
    ]
