from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from responses.models import ResponseAuditEvent, Submission
from responses.services import start_submission
from surveys import services
from surveys.models import (
    ChoiceIdentity,
    Question,
    QuestionIdentity,
    SectionIdentity,
    Survey,
    SurveyVersion,
)
from django.core.exceptions import ValidationError

from surveys.diff import questionnaire_diff
from surveys.presentation import (
    build_submission_presentation,
    content_changed,
    questionnaire_signature,
    resolved_version,
)
from surveys.publication import (
    delete_retired_version,
    discard_draft_changes,
    publication_intent,
    publish_survey,
    restore_version_to_draft,
)


class LivePresentationVersioningTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='live-versioning@example.com',
        )
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Live presentation study',
            summary='Stable content with mutable presentation.',
        )
        draft = self.survey.draft_version
        section = draft.sections.get()
        self.first, revision = services.add_question(
            section.id,
            Question.Type.SHORT_TEXT,
            draft.revision,
        )
        self.second, revision = services.add_question(
            section.id,
            Question.Type.SHORT_TEXT,
            revision,
        )
        self.active, self.draft = publish_survey(
            self.survey.id,
            self.owner,
            revision,
        )
        self.survey.refresh_from_db()

    def _update_second(self, *, prompt=None, required=False):
        question = self.draft.sections.get().questions.get(
            identity_id=self.second.identity_id,
        )
        question, revision = services.update_question(
            question.id,
            self.draft.revision,
            {
                'type': question.type,
                'prompt': prompt or question.prompt,
                'help_text': question.help_text,
                'required': required,
                'randomize_choices': False,
            },
            question.config,
            [],
            [],
        )
        self.draft.refresh_from_db()
        return question, revision

    def test_live_controls_change_both_presentations_without_mutating_snapshots(self):
        active_questions = list(
            self.active.sections.get().questions.order_by('order')
        )
        draft_questions = list(self.draft.sections.get().questions.order_by('order'))
        active_legacy = [(item.id, item.order, item.required) for item in active_questions]
        draft_legacy = [(item.id, item.order, item.required) for item in draft_questions]
        signature = questionnaire_signature(self.active)

        draft_second, revision = self._update_second(required=True)
        services.move_question(draft_second.id, revision, 'up')

        self.assertEqual(questionnaire_signature(self.active), signature)
        self.assertEqual(questionnaire_signature(self.draft), signature)
        self.assertFalse(content_changed(self.draft, self.active))
        self.assertEqual(publication_intent(self.survey, self.draft)['action'], 'unchanged')
        self.assertEqual(
            [
                (item.id, item.order, item.required)
                for item in self.active.sections.get().questions.order_by('order')
            ],
            active_legacy,
        )
        self.assertEqual(
            [
                (item.id, item.order, item.required)
                for item in self.draft.sections.get().questions.order_by('order')
            ],
            draft_legacy,
        )
        resolved_active = [
            question
            for section in resolved_version(self.active)
            for question in section.questions.all()
        ]
        self.assertEqual(resolved_active[0].identity_id, self.second.identity_id)
        self.assertTrue(resolved_active[0].required)

    def test_submission_presentation_does_not_change_after_start(self):
        draft_second, revision = self._update_second(required=True)
        submission = start_submission(self.survey, None, 'stable-presentation')
        presented = {
            question['id']: question
            for section in submission.presentation['sections']
            for question in section['questions']
        }
        active_second = self.active.sections.get().questions.get(
            identity_id=self.second.identity_id,
        )
        self.assertTrue(presented[str(active_second.id)]['required'])

        services.update_question(
            draft_second.id,
            revision,
            {
                'type': draft_second.type,
                'prompt': draft_second.prompt,
                'help_text': draft_second.help_text,
                'required': False,
                'randomize_choices': False,
            },
            draft_second.config,
            [],
            [],
        )
        submission.refresh_from_db()
        self.assertTrue(
            next(
                question
                for section in submission.presentation['sections']
                for question in section['questions']
                if question['id'] == str(active_second.id)
            )['required']
        )

    def test_changed_empty_version_is_replaced_without_renumbering(self):
        old_active_id = self.active.id
        _, revision = self._update_second(prompt='Changed before any response')

        replacement, next_draft = publish_survey(
            self.survey.id,
            self.owner,
            revision,
        )

        self.assertEqual(replacement.number, 1)
        self.assertNotEqual(replacement.id, old_active_id)
        self.assertFalse(SurveyVersion.objects.filter(pk=old_active_id).exists())
        self.assertEqual(next_draft.number, 2)
        self.assertEqual(replacement.title_snapshot, self.survey.title)

    def test_first_start_freezes_version_and_new_content_publishes_separately(self):
        submission = start_submission(self.survey, None, 'freeze-version')
        self.active.refresh_from_db()
        self.assertTrue(self.active.has_response_history)
        _, revision = self._update_second(prompt='Changed after a start')

        second_version, _ = publish_survey(
            self.survey.id,
            self.owner,
            revision,
        )

        self.active.refresh_from_db()
        submission.refresh_from_db()
        self.assertEqual(self.active.status, SurveyVersion.Status.RETIRED)
        self.assertEqual(second_version.number, 2)
        self.assertEqual(submission.version_id, self.active.id)

    def test_restore_and_delete_retired_version_preserve_audit(self):
        submission = start_submission(self.survey, None, 'delete-version')
        _, revision = self._update_second(prompt='Version two content')
        second_version, current_draft = publish_survey(
            self.survey.id,
            self.owner,
            revision,
        )

        source, restored = restore_version_to_draft(
            self.survey.id,
            self.active.id,
            self.owner,
            current_draft.revision,
        )
        restored_question = restored.sections.get().questions.get(
            identity_id=self.second.identity_id,
        )
        source_question = source.sections.get().questions.get(
            identity_id=self.second.identity_id,
        )
        self.assertEqual(restored_question.prompt, source_question.prompt)
        self.assertEqual(restored_question.identity_id, source_question.identity_id)
        self.assertEqual(second_version.status, SurveyVersion.Status.PUBLISHED)

        deleted = delete_retired_version(
            self.survey.id,
            self.active.id,
            self.owner,
        )
        self.assertEqual(deleted, 1)
        self.assertFalse(Submission.objects.filter(pk=submission.pk).exists())
        self.assertTrue(
            ResponseAuditEvent.objects.filter(
                submission_id=submission.id,
                metadata__reason='retired_version_deleted',
            ).exists()
        )

    def test_retired_version_delete_confirmation_centers_its_card(self):
        SurveyVersion.objects.filter(pk=self.active.pk).update(
            status=SurveyVersion.Status.RETIRED,
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                'survey_version_delete',
                args=(self.survey.id, self.active.id),
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="shell narrow-shell completion-shell"',
        )

    def test_presentation_fingerprint_is_stable_under_question_randomization(self):
        section = self.active.sections.get()
        section.identity.randomize_questions = True
        section.identity.save(update_fields=('randomize_questions',))
        self.active.refresh_from_db()

        fingerprints = {
            build_submission_presentation(self.active)['fingerprint']
            for _ in range(12)
        }

        self.assertEqual(len(fingerprints), 1)

    def test_moving_live_question_into_unpublished_section_is_blocked(self):
        # The active version has no responses yet, but the move would still drop
        # a live question from it, so the guard must fire regardless.
        self.assertFalse(self.active.has_response_history)
        new_section, revision = services.add_section(self.draft.id, self.draft.revision)
        draft_first = self.draft.sections.get(
            identity_id=self.active.sections.first().identity_id,
        ).questions.get(identity_id=self.first.identity_id)

        with self.assertRaises(ValidationError):
            services.reorder_question(draft_first.id, revision, new_section.id, 0)

        resolved_active = [
            question
            for section in resolved_version(self.active)
            for question in section.questions.all()
        ]
        self.assertEqual(len(resolved_active), 2)

    def test_moving_live_question_is_blocked_after_responses_too(self):
        start_submission(self.survey, None, 'guard-move-responses')
        self.active.refresh_from_db()
        self.assertTrue(self.active.has_response_history)
        new_section, revision = services.add_section(self.draft.id, self.draft.revision)
        draft_first = self.draft.sections.get(
            identity_id=self.active.sections.first().identity_id,
        ).questions.get(identity_id=self.first.identity_id)

        with self.assertRaises(ValidationError):
            services.reorder_question(draft_first.id, revision, new_section.id, 0)

    def test_discard_draft_resets_to_published_and_prunes_orphans(self):
        _, revision = self._update_second(prompt='Draft-only edit')
        new_section, revision = services.add_section(self.draft.id, revision)
        services.add_question(
            new_section.id,
            Question.Type.SHORT_TEXT,
            revision,
        )
        self.assertEqual(publication_intent(self.survey, self.draft)['action'], 'replace')

        self.draft.refresh_from_db()
        new_draft = discard_draft_changes(self.survey.id, self.owner, self.draft.revision)

        self.assertFalse(content_changed(new_draft, self.active))
        resolved_draft = [
            question
            for section in resolved_version(new_draft)
            for question in section.questions.all()
        ]
        self.assertEqual(len(resolved_draft), 2)
        self.assertEqual(publication_intent(self.survey, new_draft)['action'], 'unchanged')

    def test_survey_hard_delete_removes_identity_rows(self):
        survey = Survey.objects.create(
            owner=self.owner,
            title='Disposable',
            summary='No responses collected.',
        )
        # A choice question exercises the full PROTECTed identity hierarchy
        # (choice -> question -> section identities) that a naive delete trips.
        section = survey.draft_version.sections.get()
        services.add_question(
            section.id,
            Question.Type.SINGLE_CHOICE,
            survey.draft_version.revision,
        )
        survey_id = survey.id

        survey.delete()

        self.assertFalse(Survey.objects.filter(pk=survey_id).exists())
        self.assertFalse(SurveyVersion.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(SectionIdentity.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(QuestionIdentity.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(ChoiceIdentity.objects.filter(survey_id=survey_id).exists())

    def test_publish_diff_classifies_content_against_the_live_version(self):
        section = self.draft.sections.get()
        draft_second = section.questions.get(identity_id=self.second.identity_id)
        _, revision = services.update_question(
            draft_second.id,
            self.draft.revision,
            {
                'type': draft_second.type,
                'prompt': 'Reworded prompt',
                'help_text': draft_second.help_text,
                'required': False,
                'randomize_choices': False,
            },
            draft_second.config,
            [],
            [],
        )
        draft_first = section.questions.get(identity_id=self.first.identity_id)
        revision = services.delete_question(draft_first.id, revision)
        services.add_question(section.id, Question.Type.LONG_TEXT, revision)
        self.draft.refresh_from_db()

        diff = questionnaire_diff(self.draft, self.active)

        self.assertTrue(diff['has_changes'])
        self.assertEqual(diff['counts']['questions_added'], 1)
        self.assertEqual(diff['counts']['questions_removed'], 1)
        self.assertEqual(diff['counts']['questions_changed'], 1)
        entry = next(
            question
            for section_entry in diff['sections']
            for question in section_entry['questions']
            if question['status'] == 'changed'
        )
        self.assertEqual([change['label'] for change in entry['changes']], ['Prompt'])
        self.assertEqual(entry['changes'][0]['to'], 'Reworded prompt')

    def test_publish_diff_reports_no_changes_for_live_only_edits(self):
        # Reordering and required state apply live, so publishing changes nothing.
        draft_second = self.draft.sections.get().questions.get(
            identity_id=self.second.identity_id,
        )
        _, revision = self._update_second(required=True)
        services.move_question(draft_second.id, revision, 'up')
        self.draft.refresh_from_db()

        diff = questionnaire_diff(self.draft, self.active)

        self.assertFalse(diff['has_changes'])

    def test_swapping_a_choice_keeps_snapshot_orders_unique(self):
        section = self.draft.sections.get()
        question, revision = services.add_question(
            section.id,
            Question.Type.SINGLE_CHOICE,
            self.draft.revision,
        )
        kept, dropped = list(question.choices.order_by('order'))

        # Drop one option and add another in the same save — the new row would
        # otherwise collide with the not-yet-deleted row's snapshot order.
        services.update_question(
            question.id,
            revision,
            {
                'type': question.type,
                'prompt': question.prompt,
                'help_text': '',
                'required': False,
                'randomize_choices': False,
            },
            question.config,
            ['Kept option', 'Fresh option'],
            [],
            choice_identity_ids=[str(kept.identity_id), ''],
        )

        question.refresh_from_db()
        labels = [choice.label for choice in question.choices.order_by('order')]
        orders = [choice.order for choice in question.choices.order_by('order')]
        self.assertEqual(labels, ['Kept option', 'Fresh option'])
        self.assertEqual(orders, [1, 2])
        self.assertFalse(question.choices.filter(identity_id=dropped.identity_id).exists())

    def test_survey_queryset_delete_tears_down_identity_hierarchy(self):
        survey = Survey.objects.create(
            owner=self.owner,
            title='Bulk disposable',
            summary='Deleted via queryset.',
        )
        section = survey.draft_version.sections.get()
        services.add_question(
            section.id,
            Question.Type.SINGLE_CHOICE,
            survey.draft_version.revision,
        )
        survey_id = survey.id

        Survey.objects.filter(pk=survey_id).delete()

        self.assertFalse(Survey.objects.filter(pk=survey_id).exists())
        self.assertFalse(SectionIdentity.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(ChoiceIdentity.objects.filter(survey_id=survey_id).exists())

    def test_survey_hard_delete_retains_reward_tombstone(self):
        from rewards.models import PointTransaction

        survey = Survey.objects.create(
            owner=self.owner,
            title='Guarded',
            summary='Has a retained reward transaction.',
        )
        section = survey.draft_version.sections.get()
        services.add_question(
            section.id,
            Question.Type.SHORT_TEXT,
            survey.draft_version.revision,
        )
        reward = PointTransaction.objects.create(
            user=self.owner,
            amount=10,
            reason=PointTransaction.Reason.SURVEY_COMPLETION,
            idempotency_key='guarded-survey-reward',
            survey=survey,
        )
        survey_id = survey.id

        survey.delete()

        self.assertFalse(Survey.objects.filter(pk=survey_id).exists())
        self.assertFalse(SurveyVersion.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(SectionIdentity.objects.filter(survey_id=survey_id).exists())
        self.assertFalse(QuestionIdentity.objects.filter(survey_id=survey_id).exists())
        reward.refresh_from_db()
        self.assertIsNone(reward.survey)
