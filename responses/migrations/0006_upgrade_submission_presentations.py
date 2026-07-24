from django.db import migrations


def upgrade_presentations(apps, schema_editor):
    Submission = apps.get_model('responses', 'Submission')
    Question = apps.get_model('surveys', 'Question')
    BranchRule = apps.get_model('surveys', 'BranchRule')

    for submission in Submission.objects.iterator():
        presentation = dict(submission.presentation or {})
        if presentation.get('schema') == 2:
            continue
        questions = {
            str(question.id): question
            for question in Question.objects.filter(
                section__version_id=submission.version_id,
            )
        }
        # Stamp each presented question with its required flag so the new
        # snapshot-driven completion/validation code can read it back.
        for section_data in presentation.get('sections', []):
            for question_data in section_data.get('questions', []):
                question = questions.get(question_data.get('id'))
                question_data['required'] = bool(question and question.required)
        branch_rules = [
            {
                'id': str(rule.id),
                'source_question_id': str(rule.source_question_id),
                'source_section_id': str(rule.source_question.section_id),
                'operator': rule.operator,
                'compare_value': rule.compare_value,
                'action': rule.action,
                'target_section_id': (
                    str(rule.target_section_id) if rule.target_section_id else None
                ),
                'order': rule.order,
            }
            for rule in BranchRule.objects.filter(
                version_id=submission.version_id,
            ).select_related('source_question').order_by('order')
        ]
        # These submissions were snapshotted before the presentation-fingerprint
        # existed, and the pre-feature snapshot can't be replayed through the
        # live layer to reproduce the runtime fingerprint. Leave it blank so the
        # analytics "multiple presentation configurations" check (which ignores
        # empty fingerprints) doesn't treat legacy vs. new submissions of an
        # unchanged version as a spurious difference.
        presentation.update(
            {
                'schema': 2,
                'branch_rules': branch_rules,
                'fingerprint': '',
            }
        )
        Submission.objects.filter(pk=submission.pk).update(
            presentation=presentation,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('responses', '0005_alter_submission_source'),
        ('surveys', '0012_require_snapshot_identities'),
    ]

    operations = [
        migrations.RunPython(
            upgrade_presentations,
            migrations.RunPython.noop,
        ),
    ]
