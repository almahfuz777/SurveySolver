"""Drop the version-scoped tables superseded by the live survey schema.

Branching, response limits and targeting moved to SurveyBranchRule,
SurveyVersion.response_limit and SurveyEligibilityCriteria. Migration 0011
backfilled the live rows, and nothing has written these tables since.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0012_require_snapshot_identities'),
        # Reads surveys.BranchRule historically.
        # It shares this migration's other dependency, so without this edge the drop could be ordered ahead of it.
        ('responses', '0006_upgrade_submission_presentations'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='branchrule',
            name='surveys_branch_rule_order_unique',
        ),
        migrations.RemoveConstraint(
            model_name='quota',
            name='surveys_quota_name_unique',
        ),
        migrations.DeleteModel(
            name='BranchRule',
        ),
        migrations.DeleteModel(
            name='EligibilityCriteria',
        ),
        migrations.DeleteModel(
            name='Quota',
        ),
    ]
