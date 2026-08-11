from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.branching import Action, Operator
from surveys.models import Question, QuestionIdentity, Survey
from surveys.publication import publish_survey
from surveys import services as survey_services
from surveys.lifecycle import set_response_collection

from rewards.models import PointTransaction
from rewards.policy import PROFILE_COMPLETION_BONUS

from responses.models import Answer, Submission
from responses.services import AuthenticationRequired, hash_session_key, start_submission


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
        )
        QuestionIdentity.objects.filter(
            pk=self.draft_question.identity_id,
        ).update(required=True)
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
        self.survey.refresh_from_db()

    def screener_post(self, **overrides):
        """Screener answers that satisfy the default `target_survey` criteria."""
        answers = {
            'birth_date': '2002-04-10',
            'education_level': 'undergraduate',
            'country': 'BD',
            'employment_status': 'student',
        }
        answers.update(overrides)
        return {f'eligibility-{name}': value for name, value in answers.items()}

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
        second_question, revision = survey_services.update_question(
            second_question.id,
            revision,
            {
                'type': Question.Type.LONG_TEXT,
                'prompt': 'Explain your study routine',
                'help_text': '',
                'required': True,
                'randomize_choices': False,
            },
            {},
            [],
            [],
        )
        _, revision = survey_services.add_branch_rule(
            draft.id,
            revision,
            {
                'source_question': first_question,
                'operator': Operator.EQUALS,
                'compare_value': 'Skip follow-up',
                'action': Action.END_SURVEY,
                'target_section': None,
            },
        )
        self.published, _ = publish_survey(self.survey.id, self.owner, revision)
        self.survey.refresh_from_db()
        self.question = self.published.sections.order_by('identity__order').first().questions.get()
        return self.published.sections.order_by('identity__order').last().questions.get()

    def add_response_limit(self, limit=1):
        draft = self.survey.draft_version
        revision = survey_services.update_response_limit(
            draft.id,
            draft.revision,
            limit,
        )
        self.survey.refresh_from_db()

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

    def test_response_form_uses_responder_preview_layout(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client.get(reverse('response_form', args=[submission.id]))

        self.assertContains(response, 'class="response-intro"')
        self.assertContains(response, 'class="response-card"')
        self.assertContains(
            response,
            '<span class="response-question-number">1.</span>',
            html=True,
        )

    def test_ranking_question_renders_reorderable_items_and_preserves_posted_order(self):
        draft = self.survey.draft_version
        ranking, revision = survey_services.add_question(
            draft.sections.get().id,
            Question.Type.RANKING,
            draft.revision,
        )
        ranking, revision = survey_services.update_question(
            ranking.id,
            revision,
            {
                'type': Question.Type.RANKING,
                'prompt': 'Rank these study spaces',
                'help_text': '',
                'required': True,
                'randomize_choices': False,
            },
            {},
            ['Library', 'Study hall', 'Home'],
            [],
        )
        published, _ = publish_survey(self.survey.id, self.owner, revision)
        ranking = published.sections.get().questions.get(type=Question.Type.RANKING)
        short_text = published.sections.get().questions.get(type=Question.Type.SHORT_TEXT)
        choices = list(ranking.choices.order_by('identity__order'))
        self.start()
        submission = Submission.objects.get()

        response = self.client.get(reverse('response_form', args=[submission.id]))

        self.assertContains(response, 'data-ranking-list')
        self.assertContains(response, f'name="q_{ranking.id}"', count=3)

        ranked_ids = [str(choice.id) for choice in reversed(choices)]
        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {
                f'q_{short_text.id}': 'Quiet rooms',
                f'q_{ranking.id}': ranked_ids,
            },
        )

        self.assertRedirects(
            response,
            reverse('response_complete', args=[submission.id]),
        )
        answer = submission.answers.get(question=ranking)
        self.assertEqual(
            [item['choice_id'] for item in answer.value],
            ranked_ids,
        )

    def test_guest_can_discard_saved_progress_from_same_browser(self):
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {
                'action': 'save',
                f'q_{self.question.id}': 'Saved but no longer needed',
            },
        )

        response = self.client.post(
            reverse('response_discard', args=[submission.id]),
        )

        self.assertRedirects(response, reverse('discover'))
        self.assertFalse(Submission.objects.filter(pk=submission.pk).exists())

    def test_other_browser_cannot_discard_saved_progress(self):
        self.start()
        submission = Submission.objects.get()

        response = self.client_class().post(
            reverse('response_discard', args=[submission.id]),
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Submission.objects.filter(pk=submission.pk).exists())

    def test_completed_response_cannot_be_discarded_as_draft(self):
        self.start()
        submission = Submission.objects.get()
        self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Completed answer'},
        )

        response = self.client.post(
            reverse('response_discard', args=[submission.id]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Submission.objects.filter(pk=submission.pk).exists())

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

    def test_identified_response_shares_the_account_and_needs_consent(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save(update_fields=('identity_mode', 'updated_at'))
        respondent = get_user_model().objects.create_user(
            email='identified@example.com',
            first_name='Samira',
            last_name='Khan',
        )
        self.client.force_login(respondent)
        url = reverse('respond_survey', args=[self.survey.slug])

        page = self.client.get(url)
        invalid = self.client.post(url, {})

        # The respondent reads what is shared; there is nothing for them to type or edit.
        self.assertContains(page, 'Samira Khan')
        self.assertContains(page, 'identified@example.com')
        self.assertNotContains(page, 'name="identity_name"')
        self.assertNotContains(page, 'name="identity_email"')
        self.assertEqual(invalid.status_code, 422)
        self.assertContains(invalid, 'Confirm you agree', status_code=422)
        self.assertFalse(Submission.objects.exists())

        valid = self.client.post(url, {'identity_consent': 'yes'})

        submission = Submission.objects.get()
        self.assertRedirects(valid, reverse('response_form', args=[submission.id]))
        self.assertEqual(
            submission.identity_data,
            {'name': 'Samira Khan', 'email': 'identified@example.com'},
        )
        self.assertIsNotNone(submission.identity_consent_at)

    def test_profile_scope_discloses_and_shares_the_research_profile(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.identity_scope = Survey.IdentityScope.PROFILE
        self.survey.save()
        # Saving a profile-sharing survey turns the account requirement on by itself.
        self.assertTrue(self.survey.requires_account)
        respondent = get_user_model().objects.create_user(
            email='shares@example.com',
            first_name='Nadia',
            last_name='Rahman',
        )
        profile = respondent.profile
        profile.birth_date = date(2000, 6, 1)
        profile.gender = 'woman'
        profile.country = 'BD'
        profile.education_level = 'undergraduate'
        profile.save()
        self.client.force_login(respondent)
        url = reverse('respond_survey', args=[self.survey.slug])

        page = self.client.get(url)
        self.client.post(url, {'identity_consent': 'yes'})

        # The respondent is told the profile is shared, and it genuinely is.
        self.assertContains(page, 'Research profile')
        self.assertContains(page, 'your research profile alongside your answers')
        shared = Submission.objects.get().identity_data
        self.assertEqual(shared['name'], 'Nadia Rahman')
        labels = {row['label']: row['value'] for row in shared['profile']}
        self.assertEqual(labels['Education'], 'Undergraduate')
        self.assertEqual(labels['Country'], 'Bangladesh')
        self.assertEqual(labels['Gender'], 'Woman')

    def test_contact_scope_shares_no_research_profile(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.identity_scope = Survey.IdentityScope.CONTACT
        self.survey.save()
        respondent = get_user_model().objects.create_user(email='contact-only@example.com')
        respondent.profile.education_level = 'undergraduate'
        respondent.profile.save()
        self.client.force_login(respondent)

        self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {'identity_consent': 'yes'},
        )

        self.assertNotIn('profile', Submission.objects.get().identity_data)

    def test_a_posted_identity_cannot_override_the_account(self):
        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save(update_fields=('identity_mode', 'updated_at'))
        respondent = get_user_model().objects.create_user(
            email='real@example.com',
            first_name='Real',
            last_name='Respondent',
        )
        self.client.force_login(respondent)

        self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'identity_consent': 'yes',
                'identity_name': 'Someone Else',
                'identity_email': 'spoofed@example.com',
            },
        )

        self.assertEqual(
            Submission.objects.get().identity_data,
            {'name': 'Real Respondent', 'email': 'real@example.com'},
        )

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

    def test_targeted_guest_is_asked_every_criterion_the_survey_sets(self):
        self.target_survey(languages=['bn'], religions=['islam'])
        url = reverse('respond_survey', args=[self.survey.slug])

        page = self.client.get(url)
        invalid = self.client.post(url, {})

        self.assertContains(page, 'Eligibility check')
        for field in (
            'eligibility-birth_date',
            'eligibility-education_level',
            'eligibility-country',
            'eligibility-employment_status',
            'eligibility-religion',
            'eligibility-languages',
        ):
            self.assertContains(page, f'name="{field}"')
        self.assertEqual(invalid.status_code, 422)
        self.assertFalse(Submission.objects.exists())

    def test_screener_says_the_answers_are_not_shown_with_the_response(self):
        self.target_survey()

        anonymous = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        self.assertContains(anonymous, 'never shown next to your response')
        self.assertContains(anonymous, 'This survey is anonymous')

        self.survey.identity_mode = Survey.IdentityMode.IDENTIFIED
        self.survey.save()
        respondent = get_user_model().objects.create_user(email='screener-copy@example.com')
        self.client.force_login(respondent)

        identified = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        # The anonymity reassurance is only true when the response really is anonymous.
        self.assertContains(identified, 'never shown next to your response')
        self.assertNotContains(identified, 'This survey is anonymous')

    def test_ineligible_guest_cannot_start_targeted_survey(self):
        self.target_survey()

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            self.screener_post(country='US'),
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'do not meet', status_code=403)
        self.assertFalse(Submission.objects.exists())

    def test_guest_is_refused_on_a_criterion_beyond_the_original_five(self):
        self.target_survey(languages=['bn'])

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            self.screener_post(**{'languages': ['en']}),
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'do not meet', status_code=403)
        self.assertFalse(Submission.objects.exists())

    def test_eligible_guest_screener_is_snapshotted_separately(self):
        self.target_survey()

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            self.screener_post(),
        )

        submission = Submission.objects.get()
        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertTrue(submission.is_eligible)
        self.assertTrue(submission.eligibility_data['targeted'])
        self.assertEqual(submission.eligibility_data['country'], 'BD')
        self.assertIsNotNone(submission.eligibility_checked_at)

    def test_account_only_survey_sends_a_guest_to_sign_in(self):
        Survey.objects.filter(pk=self.survey.pk).update(requires_account=True)
        url = reverse('respond_survey', args=[self.survey.slug])

        page = self.client.get(url)
        posted = self.client.post(url, {})

        self.assertRedirects(page, f'{reverse("account_login")}?next={url}')
        self.assertRedirects(posted, f'{reverse("account_login")}?next={url}')
        self.assertFalse(Submission.objects.exists())

    def test_service_refuses_an_account_only_start_without_an_account(self):
        Survey.objects.filter(pk=self.survey.pk).update(requires_account=True)
        self.survey.refresh_from_db()

        with self.assertRaises(AuthenticationRequired):
            start_submission(self.survey, None, 'anonymous-account-only')

        self.assertFalse(Submission.objects.exists())

    def test_account_holder_can_still_answer_an_account_only_survey(self):
        Survey.objects.filter(pk=self.survey.pk).update(requires_account=True)
        self.survey.refresh_from_db()
        respondent = get_user_model().objects.create_user(email='member@example.com')
        self.client.force_login(respondent)

        response = self.start()

        submission = Submission.objects.get()
        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        self.assertEqual(submission.respondent, respondent)

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

    def test_a_future_birth_date_is_rejected_rather_than_passing_as_young(self):
        self.target_survey()

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            self.screener_post(birth_date='2030-01-01'),
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'cannot be in the future', status_code=422)
        self.assertFalse(Submission.objects.exists())

    def test_screener_answers_that_complete_a_profile_award_the_bonus(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(
            email='completing@example.com',
            first_name='Nadia',
            last_name='Rahman',
        )
        profile = respondent.profile
        profile.birth_date = date(2002, 4, 10)
        profile.gender = 'woman'
        profile.country = 'BD'
        profile.field_of_study = 'computer_science'
        profile.employment_status = 'student'
        profile.research_interests = ['learning-science']
        profile.save()
        self.client.force_login(respondent)

        self.assertEqual(PointTransaction.objects.balance_for(respondent), 0)

        self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {'eligibility-education_level': 'undergraduate'},
        )

        # Finishing a profile earns the same bonus wherever the answers were typed.
        profile.refresh_from_db()
        self.assertEqual(profile.completion_percentage, 100)
        self.assertEqual(PointTransaction.objects.balance_for(respondent), PROFILE_COMPLETION_BONUS)

    def test_screener_rejects_a_region_outside_the_answered_country(self):
        self.target_survey(regions=['BD-13'], countries=['BD', 'CA'])
        respondent = get_user_model().objects.create_user(email='mismatch@example.com')
        self.client.force_login(respondent)

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            self.screener_post(country='CA', region='BD-13'),
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'region inside your selected country', status_code=422)
        self.assertFalse(Submission.objects.exists())

    def test_targeting_a_region_also_asks_for_the_country(self):
        self.target_survey(regions=['BD-13'], countries=[], min_age=None, max_age=None,
                           education_levels=[], employment_statuses=[])

        page = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        self.assertContains(page, 'name="eligibility-region"')
        self.assertContains(page, 'name="eligibility-country"')

    def test_incomplete_profile_is_asked_only_for_the_missing_answers(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(email='incomplete@example.com')
        respondent.profile.birth_date = date(2002, 4, 10)
        respondent.profile.country = 'BD'
        respondent.profile.save()
        self.client.force_login(respondent)

        page = self.client.get(reverse('respond_survey', args=[self.survey.slug]))

        # Birth date and country are already on file, so only the rest are asked for.
        self.assertContains(page, 'name="eligibility-education_level"')
        self.assertContains(page, 'name="eligibility-employment_status"')
        self.assertNotContains(page, 'name="eligibility-birth_date"')
        self.assertNotContains(page, 'name="eligibility-country"')

    def test_screener_answers_are_saved_back_onto_the_profile(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(email='partial@example.com')
        respondent.profile.birth_date = date(2002, 4, 10)
        respondent.profile.country = 'BD'
        respondent.profile.save()
        self.client.force_login(respondent)

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'eligibility-education_level': 'undergraduate',
                'eligibility-employment_status': 'student',
            },
        )

        submission = Submission.objects.get()
        self.assertRedirects(response, reverse('response_form', args=[submission.id]))
        respondent.profile.refresh_from_db()
        self.assertEqual(respondent.profile.education_level, 'undergraduate')
        self.assertEqual(respondent.profile.employment_status, 'student')

    def test_a_refused_start_does_not_write_to_the_profile(self):
        self.target_survey()
        respondent = get_user_model().objects.create_user(email='refused@example.com')
        respondent.profile.birth_date = date(2002, 4, 10)
        respondent.profile.country = 'BD'
        respondent.profile.save()
        self.client.force_login(respondent)

        response = self.client.post(
            reverse('respond_survey', args=[self.survey.slug]),
            {
                'eligibility-education_level': 'secondary',
                'eligibility-employment_status': 'student',
            },
        )

        self.assertEqual(response.status_code, 403)
        respondent.profile.refresh_from_db()
        self.assertEqual(respondent.profile.education_level, '')
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

    def test_response_limit_is_checked_again_at_completion(self):
        self.add_response_limit(limit=1)
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
        self.assertContains(blocked, 'reached its response limit', status_code=422)
        submissions[1].refresh_from_db()
        self.assertEqual(submissions[1].status, Submission.Status.IN_PROGRESS)

    def test_full_response_limit_blocks_new_starts(self):
        self.add_response_limit(limit=1)
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
        self.assertContains(response, 'reached its response limit', status_code=403)
        self.assertEqual(Submission.objects.count(), 1)

    def test_pausing_collection_blocks_an_in_progress_completion(self):
        self.start()
        submission = Submission.objects.get()
        set_response_collection(self.survey.id, False)

        response = self.client.post(
            reverse('response_form', args=[submission.id]),
            {f'q_{self.question.id}': 'Saved for later'},
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'not accepting responses', status_code=422)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.IN_PROGRESS)
