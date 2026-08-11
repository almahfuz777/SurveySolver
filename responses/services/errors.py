"""Why a response could not be started, saved or completed."""


class ResponseUnavailable(Exception):
    pass


class ResponseValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Some answers need attention.')


class DuplicateSubmission(Exception):
    def __init__(self, submission):
        self.submission = submission
        super().__init__('A response has already been completed for this survey.')


class AuthenticationRequired(Exception):
    """An account-only survey was reached by a guest."""


class EligibilityUnknown(Exception):
    pass


class IneligibleRespondent(Exception):
    pass


class QuotaReached(Exception):
    pass
