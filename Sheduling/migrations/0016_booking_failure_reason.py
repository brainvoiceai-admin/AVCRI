# Generated migration: store exact failure reason for failed bookings (dashboard display)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Sheduling', '0015_therapistcontinuityplan'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='failure_reason',
            field=models.CharField(blank=True, help_text="Exact reason when status is 'failed' (e.g. no_preferred_slot, insufficient_therapists)", max_length=512),
        ),
    ]
