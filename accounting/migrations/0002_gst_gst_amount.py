from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='gst',
            name='gst_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14),
            preserve_default=False,
        ),
    ]
