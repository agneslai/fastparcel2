# Generated by Django 3.1.3 on 2021-05-30 07:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_auto_20210530_0620'),
    ]

    operations = [
        migrations.AddField(
            model_name='courier',
            name='paypal_email',
            field=models.EmailField(blank=True, max_length=255),
        ),
    ]