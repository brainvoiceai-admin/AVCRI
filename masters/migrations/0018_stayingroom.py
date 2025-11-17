from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0017_add_initial_therapist_grades'),
    ]

    operations = [
        migrations.CreateModel(
            name='StayingRoom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=20, unique=True, verbose_name='No')),
                ('room_desc', models.CharField(max_length=255, verbose_name='Room Description')),
                ('room_no', models.CharField(max_length=50, verbose_name='Room Number')),
                ('is_active', models.BooleanField(default=True, verbose_name='Active')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated At')),
            ],
            options={
                'verbose_name': 'Staying Room',
                'verbose_name_plural': 'Staying Rooms',
                'ordering': ['number'],
            },
        ),
    ]

