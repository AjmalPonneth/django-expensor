# Generated by Django 2.2.24 on 2021-08-13 22:52

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('expense', '0004_auto_20210809_1451'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='remark',
            unique_together={('user', 'name')},
        ),
    ]
