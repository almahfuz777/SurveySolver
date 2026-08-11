"""Matching a respondent against a survey's eligibility criteria.

One table drives everything: which criterion filters which respondent attribute. The builder, the
public catalogue and the response screener all read it, so a new criterion cannot be enforced in
one place and forgotten in another.
"""
from accounts.demographics import age_on


AGE_ATTRIBUTE = 'birth_date'

# criterion field on SurveyEligibilityCriteria -> respondent attribute it filters
SINGLE_VALUE_CRITERIA = (
    ('education_levels', 'education_level'),
    ('countries', 'country'),
    ('regions', 'region'),
    ('genders', 'gender'),
    ('employment_statuses', 'employment_status'),
    ('industries', 'industry'),
    ('income_brackets', 'income_bracket'),
    ('religions', 'religion'),
    ('ethnicities', 'ethnicity'),
)

# The respondent holds several values and matches when any one of them is accepted.
MULTI_VALUE_CRITERIA = (
    ('languages', 'languages'),
)

# Age is a numeric range rather than a list of accepted values, so it is named separately.
AGE_CRITERIA = ('min_age', 'max_age')

# Every list-valued criterion, in questionnaire order. Anything that enumerates criteria — the
# model's `is_targeted`, the builder form, the screener — derives from this rather than repeating it.
CRITERION_FIELDS = tuple(
    criterion for criterion, _ in SINGLE_VALUE_CRITERIA + MULTI_VALUE_CRITERIA
)


def _age_on(birth_date):
    """Whole years since birth_date, or None when the date cannot describe a living respondent.

    Shared with the profile so an implausible date — future, or centuries past — is refused the
    same way here as it is on the profile form.
    """
    return age_on(birth_date)


def targets_age(criteria):
    return criteria.min_age is not None or criteria.max_age is not None


def targeted_attributes(criteria):
    """The respondent attributes this survey actually filters on, in questionnaire order."""
    if not criteria or not criteria.is_targeted:
        return ()
    attributes = []
    if targets_age(criteria):
        attributes.append(AGE_ATTRIBUTE)
    for criterion, attribute in SINGLE_VALUE_CRITERIA + MULTI_VALUE_CRITERIA:
        if getattr(criteria, criterion):
            attributes.append(attribute)
    # A region code only means something next to its country (``BD-13``), so asking for one
    # without the other would produce a respondent record that cannot be validated.
    if 'region' in attributes and 'country' not in attributes:
        attributes.insert(attributes.index('region'), 'country')
    return tuple(attributes)


def profile_values(profile):
    """The respondent attributes above, read off a stored research profile."""
    values = {AGE_ATTRIBUTE: profile.birth_date}
    for _, attribute in SINGLE_VALUE_CRITERIA:
        value = getattr(profile, attribute)
        values[attribute] = value.code if attribute == 'country' and value else value
    for _, attribute in MULTI_VALUE_CRITERIA:
        values[attribute] = list(getattr(profile, attribute) or [])
    return values


def missing_attributes(criteria, values):
    """Targeted attributes the respondent has not answered yet."""
    return tuple(
        attribute
        for attribute in targeted_attributes(criteria)
        if not values.get(attribute)
    )


def values_match(criteria, values):
    """Whether these respondent values satisfy every criterion the survey sets."""
    if not criteria or not criteria.is_targeted:
        return True
    if targets_age(criteria):
        birth_date = values.get(AGE_ATTRIBUTE)
        if not birth_date:
            return False
        age = _age_on(birth_date)
        if age is None:
            return False
        if criteria.min_age is not None and age < criteria.min_age:
            return False
        if criteria.max_age is not None and age > criteria.max_age:
            return False
    for criterion, attribute in SINGLE_VALUE_CRITERIA:
        allowed = getattr(criteria, criterion)
        if allowed and values.get(attribute) not in allowed:
            return False
    for criterion, attribute in MULTI_VALUE_CRITERIA:
        allowed = getattr(criteria, criterion)
        if allowed and set(values.get(attribute) or []).isdisjoint(allowed):
            return False
    return True


def conflicts_with(criteria, values):
    """Whether what is already known about the respondent rules this survey out.

    Unlike :func:`values_match` an unanswered attribute is not a conflict — the respondent is asked
    for it on the landing page instead of being quietly dropped from the catalogue.
    """
    if not criteria or not criteria.is_targeted:
        return False
    birth_date = values.get(AGE_ATTRIBUTE)
    if targets_age(criteria) and birth_date:
        age = _age_on(birth_date)
        if age is None:
            return True
        if criteria.min_age is not None and age < criteria.min_age:
            return True
        if criteria.max_age is not None and age > criteria.max_age:
            return True
    for criterion, attribute in SINGLE_VALUE_CRITERIA:
        allowed = getattr(criteria, criterion)
        value = values.get(attribute)
        if allowed and value and value not in allowed:
            return True
    for criterion, attribute in MULTI_VALUE_CRITERIA:
        allowed = getattr(criteria, criterion)
        held = values.get(attribute) or []
        if allowed and held and set(held).isdisjoint(allowed):
            return True
    return False
