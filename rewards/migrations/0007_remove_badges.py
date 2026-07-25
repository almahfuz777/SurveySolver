from django.db import migrations


class Migration(migrations.Migration):
    """Drop the placeholder badge tables.

    The badge program (thresholds, categories, and how awards relate to point
    spending) has not been designed yet, so the seeded 1/5/25/100 completion
    badges and their awards are removed rather than left dormant. A future
    rewards milestone introduces its own models.
    """

    dependencies = [
        ('rewards', '0006_remove_pointtransaction_rewards_transaction_context_valid_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='badgeaward',
            name='rewards_one_badge_award_per_user',
        ),
        migrations.RemoveField(
            model_name='badgeaward',
            name='badge',
        ),
        migrations.RemoveField(
            model_name='badgeaward',
            name='user',
        ),
        migrations.DeleteModel(name='BadgeAward'),
        migrations.DeleteModel(name='Badge'),
    ]
