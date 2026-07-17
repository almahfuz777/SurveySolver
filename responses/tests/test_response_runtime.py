from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import BranchRule, Question, Survey
from surveys.publication import publish_survey
from surveys import services as survey_services

from responses.models import Answer, Submission
from responses.services import hash_session_key


class ResponseRuntimeTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='researcher@example.com',
            password='correct-horse-battery-staple',
        )
        self.survey = Survey.objects.create(
            owner=self.owner,
            title='Student wellbeing study',
            summary='A short study about student experiences.',
        )
        draft = self.survey.draft_version
        self.draft_question = Question.objects.create(
            section=draft.sections.get(),
            type=Question.Type.SHORT_TEXT,
            prompt='What helps you focus?',
            required=True,
            order=1,
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, draft.revision)
        self.survey.refresh_from_db()
        self.question = Question.objects.get(section__version=self.published)

    def start(self):
        return self.client.post(reverse('respond_survey', args=[self.survey.slug]))

    def target_survey(self, **overrides):
        draft = self.survey.draft_version
        values = {
            'min_age': 18,
            'max_age': 30,
            'education_levels': ['undergraduate'],
            'countries': ['BD'],
            'genders': [],
            'employment_statuses': ['student'],
        }
        values.update(overrides)
        _, revision = survey_services.update_eligibility(
            draft.id,
            draft.revision,
            values,
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, revision)
        self.survey.refresh_from_db()
        self.question = Question.objects.get(section__version=self.published)

    def add_branched_section(self):
        draft = self.survey.draft_version
        first_question = draft.sections.get().questions.get()
        second_section, revision = survey_services.add_section(
            draft.id,
            draft.revision,
        )
        second_question, revision = survey_services.add_question(
            second_section.id,
            Question.Type.LONG_TEXT,
            revision,
        )
        second_question.prompt = 'Explain your study routine'
        second_question.required = True
        second_question.save(update_fields=('prompt', 'required'))
        _, revision = survey_services.add_branch_rule(
            draft.id,
            revision,
            {
                'source_question': first_question,
                'operator': BranchRule.Operator.EQUALS,
                'compare_value': 'Skip follow-up',
                'action': BranchRule.Action.END_SURVEY,
                'target_section': None,
            },
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, revision)
        self.survey.refresh_from_db()
        self.question = self.published.sections.order_by('order').first().questions.get()
        return self.published.sections.order_by('order').last().questions.get()

    def add_total_quota(self, limit=1):
        draft = self.survey.draft_version
        _, revision = survey_services.add_quota(
            draft.id,
            draft.revision,
            {'name': 'Total responses', 'limit': limit, 'is_active': True},
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, revision)
        self.survey.refresh_from_db()
        self.question = Question.objects.get(section__version=self.published)

    def test_guest_response_is_bound_to_published_version_and_session(self):
        response = self.start()

        self.assertRedirects(response, reverse('response_form', args=[Submission.objects.get().id]))
        submission = Submission.objects.get()
        self.assertEqual(submission.version, self.published)
        self.assertIsNone(submission.respondent)
        self.assertEqual(
            submission.session_key_hash,
            hash_session_key(self.client.session.session_key),
        )
        self.assertNotEqual(submission.session_key_hash, self.client.session.session_key)

    def test_valid_guest_answers_are_normalized_and_submission_is_completed(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': '  Quiet study rooms  '},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.COMPLETED)
        self.assertIsNotNone(submission.completed_at)
        self.assertEqual(submission.answers.get().value, 'Quiet study rooms')

    def test_invalid_answers_do_not_create_partial_results(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(reverse('response_form', args=[submission.id]), {})

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'This question is required.', status_code=422)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.IN_PROGRESS)
        self.assertFalse(Answer.objects.exists())

    def test_authenticated_start_records_platform_respondent(self):
        respondent = get_user_model().objects.create_user(
            email='respondent@example.com',
            password='correct-horse-battery-staple',
        )
        self.client.force_login(respondent)

        self.start()

        self.assertEqual(Submission.objects.get().respondent, respondent)

    def test_another_browser_cannot_open_guest_submission(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client_class().get(reverse('response_form', args=[submission.id]))

        self.assertEqual(response.status_code, 403)

    def test_in_progress_response_uses_original_version_after_republication(self):
        self.start()
        submission = Submission.objects.get()
        next_draft = self.survey.draft_version
        Question.objects.create(
            section=next_draft.sections.get(),
            type=Question.Type.LONG_TEXT,
            prompt='What should universities improve?',
            order=2,
        )
        publish_survey(self.survey.id, self.owner, next_draft.revision)

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Library access'},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        submission.refresh_from_db()
        self.assertEqual(submission.version, self.published)
        self.assertEqual(submission.answers.count(), 1)

    def test_invitation_only_survey_is_not_publicly_startable(self):
        self.survey.visibility = Survey.Visibility.INVITATION_ONLY
        self.survey.save(update_fields=('visibility', 'updated_at'))

        response = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        self.assertEqual(response.status_code, 404)

    def test_identified_response_requires_disclosed_identity_and_consent(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save(update_fields=('identity_mode', 'updated_at'))
        respondent = get_user_model().objects.create_user(email='identified@example.com')
        self.client.force_login(respondent)
        url = reverse('respond_survey', args=[self.survey.slug])

        invalid = self.client.post(
            url,
            {'identity_name': '', 'identity_email': 'invalid'},
        )

        self.assertEqual(invalid.status_code, 422)
        self.assertContains(invalid, 'Consent is required', status_code=422)
        self.assertFalse(Submission.objects.exists())

        valid = self.client.post(
            url,
            {
                'identity_name': '  Samira Khan  ',
                'identity_email': 'SAMIRA@example.com',
                'identity_consent': 'yes',
            },
        )

        submission = Submission.objects.get()
        self.assertRedirects(valid, reverse('response_form', args=[submission.id]))
        self.assertEqual(
            submission.identity_data,
            {'name': 'Samira Khan', 'email': 'samira@example.com'},
        )
        self.assertIsNotNone(submission.identity_consent_at)

    def test_identified_survey_requires_authentication(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save(update_fields=('identity_mode', 'updated_at'))
        url = reverse('respond_survey', args=[self.survey.slug])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('account_login')}?next={url}")

    def test_completed_guest_is_returned_to_existing_response(self):
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Library'},
        )

        response = self.start()

        self.assertRedirects(
            response,
            reverse('response_form', args=[submission.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(Submission.objects.count(), 1)

    def test_authenticated_duplicate_is_prevented_across_browser_sessions(self):
        respondent = get_user_model().objects.create_user(email='repeat@example.com')
        self.client.force_login(respondent)
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Quiet room'},
        )
        other_browser = self.client_class()
        other_browser.force_login(respondent)

        response = other_browser.post(reverse('respond_survey', args=[self.survey.slug]))

        self.assertRedirects(
            response,
            reverse('response_form', args=[submission.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(Submission.objects.count(), 1)

    def test_guest_can_save_and_resume_progress_in_same_browser(self):
        self.start()
        submission = Submission.objects.get()

        saved = self.client.post(
            reverse('response_form', args=[submission.id]),
            {
                f'q_{self.question.id}': 'Campus library',
                'action': 'save',
            },
        )

        self.assertRedirects(saved, reverse('response_form', args=[submission.id]))
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.IN_PROGRESS)
        self.assertEqual(submission.answers.get().value, 'Campus library')
        resumed = self.client.get(reverse('response_form', args=[submission.id]))
        self.assertContains(resumed, 'value="Campus library"')

    def test_required_answers_may_be_blank_while_saving_progress(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {'action': 'save'},
        )

        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertFalse(submission.answers.exists())

    def test_authenticated_progress_resumes_in_another_browser(self):
        respondent = get_user_model().objects.create_user(email='resume@example.com')
        self.client.force_login(respondent)
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Study hall', 'action': 'save'},
        )
        other_browser = self.client_class()
        other_browser.force_login(respondent)

        response = other_browser.post(reverse('respond_survey', args=[self.survey.slug]))

        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertEqual(Submission.objects.count(), 1)

    def test_submission_replaces_saved_draft_answers_atomically(self):
        self.start()
        submission = Submission.objects.get()
        url = reverse('response_form', args=[submission.id])
        self.client.post(
            url,
            {f'q_{self.question.id}': 'Library', 'action': 'save'},
        )

        response = self.client.post(
            url,
            {f'q_{self.question.id}': 'Home', 'action': 'submit'},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        self.assertEqual(submission.answers.count(), 1)
        self.assertEqual(submission.answers.get().value, 'Home')

    def test_targeted_guest_must_complete_generated_screener(self):
        self.target_survey()
        url = reverse('respond_survey', args=[self.survey.slug])

        page = self.client.get(url)
        invalid = self.client.post(url, {})

        self.assertContains(page, 'Eligibility check')
        self.assertContains(page, 'name="eligibility_birth_date"')
        self.assertEqual(invalid.status_code, 422)
        self.assertContains(invalid, 'Select your education level', status_code=422)
        self.assertFalse(Submission.objects.exists())

    def test_ineligible_guest_cannot_start_targeted_survey(self):
        self.target_survey()

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'eligibility_birth_date': '2002-04-10',
                'eligibility_education_level': 'undergraduate',
                'eligibility_country': 'US',
                'eligibility_employment_status': 'student',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'does not match', status_code=403)
        self.assertFalse(Submission.objects.exists())

    def test_eligible_guest_screener_is_snapshotted_separately(self):
        self.target_survey()

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'eligibility_birth_date': '2002-04-10',
                'eligibility_education_level': 'undergraduate',
                'eligibility_country': 'BD',
                'eligibility_employment_status': 'student',
            },
        )

        submission = Submission.objects.get()
        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertTrue(submission.is_eligible)
        self.assertTrue(submission.eligibility_data['targeted'])
        self.assertEqual(submission.eligibility_data['country'], 'BD')
        self.assertIsNotNone(submission.eligibility_checked_at)

    def test_authenticated_targeting_uses_profile_not_posted_screener(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(email='eligible@example.com')
        respondent.profile.birth_date = date(2001, 5, 2)
        respondent.profile.education_level = 'undergraduate'
        respondent.profile.country = 'BD'
        respondent.profile.employment_status = 'student'
        respondent.profile.save()
        self.client.force_login(respondent)

        response = self.start()

        submission = Submission.objects.get()
        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertEqual(submission.respondent, respondent)
        self.assertEqual(submission.eligibility_data['country'], 'BD')

    def test_incomplete_authenticated_profile_cannot_use_guest_screener(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(email='incomplete@example.com')
        self.client.force_login(respondent)

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'eligibility_birth_date': '2002-04-10',
                'eligibility_education_level': 'undergraduate',
                'eligibility_country': 'BD',
                'eligibility_employment_status': 'student',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Complete the required research profile', status_code=403)
        self.assertFalse(Submission.objects.exists())

    def test_matching_end_branch_skips_later_required_sections(self):
        second_question = self.add_branched_section()
        self.start()
        submission = Submission.objects.get()
        form_page = self.client.get(reverse('response_form', args=[submission.id]))

        self.assertContains(form_page, 'response-branch-rules')
        self.assertContains(form_page, f'data-question-id="{self.question.id}"')

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Skip follow-up'},
        )

        self.assertRedirects(response, reverse('response_complete', args=[submission.id]))
        self.assertFalse(submission.answers.filter(question=second_question).exists())

    def test_default_branch_route_validates_later_required_sections(self):
        second_question = self.add_branched_section()
        self.start()
        submission = Submission.objects.get()

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Continue'},
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'This question is required.', status_code=422)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.IN_PROGRESS)
        self.assertFalse(submission.answers.filter(question=second_question).exists())

    def test_quota_is_checked_atomically_again_at_completion(self):
        self.add_total_quota(limit=1)
        first_browser = self.client
        second_browser = self.client_class()
        first_browser.post(reverse('respond_survey', args=[self.survey.slug]))
        second_browser.post(reverse('respond_survey', args=[self.survey.slug]))
        submissions = list(Submission.objects.order_by('started_at'))
        self.assertEqual(len(submissions), 2)

        first_browser.post(
            reverse('response_form', args=[submissions[0].id]),
            {f'q_{self.question.id}': 'First response'},
        )
        blocked = second_browser.post(
            reverse('response_form', args=[submissions[1].id]),
            {f'q_{self.question.id}': 'Second response'},
        )

        self.assertEqual(blocked.status_code, 422)
        self.assertContains(blocked, 'reached its response quota', status_code=422)
        submissions[1].refresh_from_db()
        self.assertEqual(submissions[1].status, Submission.Status.IN_PROGRESS)

    def test_full_quota_blocks_new_starts(self):
        self.add_total_quota(limit=1)
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Only response'},
        )

        response = self.client_class().post(
            reverse('respond_survey', args=[self.survey.slug]),
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'reached its response quota', status_code=403)
        self.assertEqual(Submission.objects.count(), 1)
