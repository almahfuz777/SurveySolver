from django.db import migrations


ELIGIBILITY_FIELDS = (
    'min_age',
    'max_age',
    'education_levels',
    'countries',
    'regions',
    'genders',
    'employment_statuses',
    'industries',
    'income_brackets',
    'religions',
    'ethnicities',
    'languages',
)


def _ordered_versions(version_model, survey):
    versions = list(version_model.objects.filter(survey_id=survey.id).order_by('number'))
    if not versions:
        return []
    base = next((item for item in versions if item.status == 'published'), None)
    if base is None:
        base = next((item for item in versions if item.status == 'draft'), versions[-1])
    lower = sorted(
        (item for item in versions if item.number < base.number),
        key=lambda item: item.number,
        reverse=True,
    )
    higher = sorted(
        (item for item in versions if item.number > base.number),
        key=lambda item: item.number,
    )
    return [base, *higher, *lower]


def backfill_live_presentation(apps, schema_editor):
    Survey = apps.get_model('surveys', 'Survey')
    SurveyVersion = apps.get_model('surveys', 'SurveyVersion')
    Section = apps.get_model('surveys', 'Section')
    Question = apps.get_model('surveys', 'Question')
    QuestionChoice = apps.get_model('surveys', 'QuestionChoice')
    MatrixRow = apps.get_model('surveys', 'MatrixRow')
    BranchRule = apps.get_model('surveys', 'BranchRule')
    EligibilityCriteria = apps.get_model('surveys', 'EligibilityCriteria')
    SectionIdentity = apps.get_model('surveys', 'SectionIdentity')
    QuestionIdentity = apps.get_model('surveys', 'QuestionIdentity')
    ChoiceIdentity = apps.get_model('surveys', 'ChoiceIdentity')
    MatrixRowIdentity = apps.get_model('surveys', 'MatrixRowIdentity')
    SurveyBranchRule = apps.get_model('surveys', 'SurveyBranchRule')
    SurveyEligibilityCriteria = apps.get_model('surveys', 'SurveyEligibilityCriteria')
    Submission = apps.get_model('responses', 'Submission')

    for survey in Survey.objects.iterator():
        ordered_versions = _ordered_versions(SurveyVersion, survey)
        if not ordered_versions:
            continue
        base = ordered_versions[0]
        processed = []

        for version in ordered_versions:
            anchor_sections = {}
            if processed:
                previous = min(
                    processed,
                    key=lambda item: abs(item.number - version.number),
                )
                anchor_sections = {
                    item.order: item
                    for item in Section.objects.filter(version_id=previous.id)
                    .exclude(identity_id=None)
                    .order_by('order')
                }

            for section in Section.objects.filter(version_id=version.id).order_by('order'):
                anchor = anchor_sections.get(section.order)
                if anchor is not None:
                    section_identity_id = anchor.identity_id
                else:
                    section_identity_id = SectionIdentity.objects.create(
                        survey_id=survey.id,
                        order=section.order,
                        randomize_questions=section.randomize_questions,
                    ).id
                Section.objects.filter(pk=section.id).update(identity_id=section_identity_id)
                section.identity_id = section_identity_id

                anchor_questions = {}
                if anchor is not None:
                    anchor_questions = {
                        (item.order, item.type): item
                        for item in Question.objects.filter(section_id=anchor.id)
                        .exclude(identity_id=None)
                        .order_by('order')
                    }
                for question in Question.objects.filter(section_id=section.id).order_by('order'):
                    anchor_question = anchor_questions.get((question.order, question.type))
                    if anchor_question is not None:
                        question_identity_id = anchor_question.identity_id
                    else:
                        question_identity_id = QuestionIdentity.objects.create(
                            survey_id=survey.id,
                            section_identity_id=section_identity_id,
                            order=question.order,
                            required=question.required,
                            randomize_choices=question.randomize_choices,
                        ).id
                    Question.objects.filter(pk=question.id).update(
                        identity_id=question_identity_id,
                    )
                    question.identity_id = question_identity_id

                    anchor_choices = {}
                    anchor_rows = {}
                    if anchor_question is not None:
                        anchor_choices = {
                            item.order: item
                            for item in QuestionChoice.objects.filter(
                                question_id=anchor_question.id,
                            ).exclude(identity_id=None)
                        }
                        anchor_rows = {
                            item.order: item
                            for item in MatrixRow.objects.filter(
                                question_id=anchor_question.id,
                            ).exclude(identity_id=None)
                        }
                    for choice in QuestionChoice.objects.filter(
                        question_id=question.id,
                    ).order_by('order'):
                        anchor_choice = anchor_choices.get(choice.order)
                        choice_identity_id = (
                            anchor_choice.identity_id
                            if anchor_choice is not None
                            else ChoiceIdentity.objects.create(
                                survey_id=survey.id,
                                question_identity_id=question_identity_id,
                                order=choice.order,
                            ).id
                        )
                        QuestionChoice.objects.filter(pk=choice.id).update(
                            identity_id=choice_identity_id,
                        )
                    for row in MatrixRow.objects.filter(
                        question_id=question.id,
                    ).order_by('order'):
                        anchor_row = anchor_rows.get(row.order)
                        row_identity_id = (
                            anchor_row.identity_id
                            if anchor_row is not None
                            else MatrixRowIdentity.objects.create(
                                survey_id=survey.id,
                                question_identity_id=question_identity_id,
                                order=row.order,
                            ).id
                        )
                        MatrixRow.objects.filter(pk=row.id).update(
                            identity_id=row_identity_id,
                        )
            processed.append(version)

        # The base version is the sole source for current presentation state.
        for section in Section.objects.filter(version_id=base.id):
            SectionIdentity.objects.filter(pk=section.identity_id).update(
                order=section.order,
                randomize_questions=section.randomize_questions,
            )
            for question in Question.objects.filter(section_id=section.id):
                QuestionIdentity.objects.filter(pk=question.identity_id).update(
                    section_identity_id=section.identity_id,
                    order=question.order,
                    required=question.required,
                    randomize_choices=question.randomize_choices,
                )
                for choice in QuestionChoice.objects.filter(question_id=question.id):
                    ChoiceIdentity.objects.filter(pk=choice.identity_id).update(
                        order=choice.order,
                    )
                for row in MatrixRow.objects.filter(question_id=question.id):
                    MatrixRowIdentity.objects.filter(pk=row.identity_id).update(
                        order=row.order,
                    )

        base_questions = {
            item.id: item
            for item in Question.objects.filter(section__version_id=base.id)
        }
        base_sections = {
            item.id: item
            for item in Section.objects.filter(version_id=base.id)
        }
        for rule in BranchRule.objects.filter(version_id=base.id).order_by('order'):
            source = base_questions.get(rule.source_question_id)
            if source is None:
                continue
            compare_choice_id = None
            if rule.compare_value:
                matching_choice = QuestionChoice.objects.filter(
                    question_id=source.id,
                    label=rule.compare_value,
                ).first()
                if matching_choice is not None:
                    compare_choice_id = matching_choice.identity_id
            target = base_sections.get(rule.target_section_id)
            SurveyBranchRule.objects.create(
                survey_id=survey.id,
                source_question_identity_id=source.identity_id,
                operator=rule.operator,
                compare_value=rule.compare_value,
                compare_choice_identity_id=compare_choice_id,
                action=rule.action,
                target_section_identity_id=target.identity_id if target else None,
                order=rule.order,
            )

        source_criteria = EligibilityCriteria.objects.filter(version_id=base.id).first()
        if source_criteria is not None:
            SurveyEligibilityCriteria.objects.create(
                survey_id=survey.id,
                **{
                    field: getattr(source_criteria, field)
                    for field in ELIGIBILITY_FIELDS
                },
            )
        Survey.objects.filter(pk=survey.id).update(response_limit=base.response_limit)
        SurveyVersion.objects.filter(
            survey_id=survey.id,
        ).exclude(status='draft').update(title_snapshot=survey.title)
        history_ids = Submission.objects.filter(
            survey_id=survey.id,
        ).values_list('version_id', flat=True).distinct()
        SurveyVersion.objects.filter(id__in=history_ids).update(
            has_response_history=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('responses', '0005_alter_submission_source'),
        ('surveys', '0010_live_presentation_schema'),
    ]

    operations = [
        migrations.RunPython(
            backfill_live_presentation,
            migrations.RunPython.noop,
        ),
    ]
