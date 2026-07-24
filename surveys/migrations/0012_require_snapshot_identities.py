import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('surveys', '0011_backfill_live_presentation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='section',
            name='identity',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='snapshots',
                to='surveys.sectionidentity',
            ),
        ),
        migrations.AlterField(
            model_name='question',
            name='identity',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='snapshots',
                to='surveys.questionidentity',
            ),
        ),
        migrations.AlterField(
            model_name='questionchoice',
            name='identity',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='snapshots',
                to='surveys.choiceidentity',
            ),
        ),
        migrations.AlterField(
            model_name='matrixrow',
            name='identity',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='snapshots',
                to='surveys.matrixrowidentity',
            ),
        ),
    ]
