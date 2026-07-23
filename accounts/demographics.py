"""Shared closed-choice demographic vocabularies.

Both the respondent profile (accounts) and survey eligibility targeting
(surveys) draw their options from here so the two sides always match on the
exact same values. Everything is a closed choice set — no free text.

Region/subdivision options come from ``pycountry`` (ISO 3166-2). The code
itself carries the country (e.g. ``BD-13``), so a stored region is unambiguous
without also storing the country.
"""

from functools import lru_cache

import pycountry


# --- Languages (respondents may speak several — stored as a list) -----------
LANGUAGE_CHOICES = (
    ('en', 'English'),
    ('bn', 'Bangla'),
    ('hi', 'Hindi'),
    ('ur', 'Urdu'),
    ('ar', 'Arabic'),
    ('zh', 'Chinese (Mandarin)'),
    ('es', 'Spanish'),
    ('fr', 'French'),
    ('pt', 'Portuguese'),
    ('ru', 'Russian'),
    ('de', 'German'),
    ('ja', 'Japanese'),
    ('ko', 'Korean'),
    ('id', 'Indonesian'),
    ('ms', 'Malay'),
    ('ta', 'Tamil'),
    ('te', 'Telugu'),
    ('mr', 'Marathi'),
    ('pa', 'Punjabi'),
    ('gu', 'Gujarati'),
    ('fa', 'Persian'),
    ('tr', 'Turkish'),
    ('vi', 'Vietnamese'),
    ('th', 'Thai'),
    ('it', 'Italian'),
    ('nl', 'Dutch'),
    ('pl', 'Polish'),
    ('uk', 'Ukrainian'),
    ('sw', 'Swahili'),
    ('ha', 'Hausa'),
    ('yo', 'Yoruba'),
    ('am', 'Amharic'),
    ('other', 'Other language'),
)

# --- Industry / sector ------------------------------------------------------
INDUSTRY_CHOICES = (
    ('agriculture', 'Agriculture & farming'),
    ('construction', 'Construction & real estate'),
    ('education', 'Education & research'),
    ('energy', 'Energy & utilities'),
    ('finance', 'Finance, banking & insurance'),
    ('government', 'Government & public sector'),
    ('healthcare', 'Healthcare & pharmaceuticals'),
    ('hospitality', 'Hospitality, travel & tourism'),
    ('it', 'Information technology & software'),
    ('legal', 'Legal & professional services'),
    ('manufacturing', 'Manufacturing & engineering'),
    ('marketing', 'Marketing, media & advertising'),
    ('nonprofit', 'Non-profit & NGO'),
    ('retail', 'Retail & e-commerce'),
    ('telecom', 'Telecommunications'),
    ('transport', 'Transport & logistics'),
    ('arts', 'Arts, culture & entertainment'),
    ('science', 'Science & biotechnology'),
    ('student', 'Student (not yet in a sector)'),
    ('other', 'Other industry'),
    ('prefer_not_to_say', 'Prefer not to say'),
)

# --- Field of study ---------------------------------------------------------
FIELD_OF_STUDY_CHOICES = (
    ('computer_science', 'Computer science'),
    ('data_science', 'Data science & AI'),
    ('engineering', 'Engineering'),
    ('mathematics', 'Mathematics & statistics'),
    ('physics', 'Physics'),
    ('chemistry', 'Chemistry'),
    ('biology', 'Biology & life sciences'),
    ('environmental_science', 'Environmental science'),
    ('medicine', 'Medicine'),
    ('nursing', 'Nursing & allied health'),
    ('pharmacy', 'Pharmacy'),
    ('public_health', 'Public health'),
    ('psychology', 'Psychology'),
    ('sociology', 'Sociology & anthropology'),
    ('economics', 'Economics'),
    ('business', 'Business & management'),
    ('finance', 'Finance & accounting'),
    ('law', 'Law'),
    ('political_science', 'Political science'),
    ('education', 'Education'),
    ('linguistics', 'Languages & linguistics'),
    ('literature', 'Literature'),
    ('history', 'History'),
    ('philosophy', 'Philosophy'),
    ('arts_design', 'Arts & design'),
    ('media_communication', 'Media & communication'),
    ('architecture', 'Architecture'),
    ('agriculture', 'Agriculture'),
    ('other', 'Other'),
    ('prefer_not_to_say', 'Prefer not to say'),
)

# --- Occupation / job family ------------------------------------------------
OCCUPATION_CHOICES = (
    ('student', 'Student'),
    ('researcher_academic', 'Researcher or academic'),
    ('engineer', 'Engineer'),
    ('software_developer', 'Software developer'),
    ('healthcare_professional', 'Healthcare professional'),
    ('educator_teacher', 'Educator or teacher'),
    ('manager_executive', 'Manager or executive'),
    ('entrepreneur', 'Entrepreneur or founder'),
    ('consultant', 'Consultant'),
    ('analyst', 'Analyst'),
    ('designer_creative', 'Designer or creative'),
    ('marketing_sales', 'Marketing or sales'),
    ('finance_professional', 'Finance professional'),
    ('legal_professional', 'Legal professional'),
    ('administrative', 'Administrative or clerical'),
    ('scientist', 'Scientist'),
    ('technician', 'Technician'),
    ('skilled_trades', 'Skilled trades'),
    ('service_worker', 'Service worker'),
    ('government_public', 'Government or public service'),
    ('nonprofit_worker', 'Non-profit worker'),
    ('retired', 'Retired'),
    ('homemaker', 'Homemaker'),
    ('other', 'Other'),
    ('prefer_not_to_say', 'Prefer not to say'),
)

# --- Monthly income band (USD-equivalent, self-reported) --------------------
INCOME_CHOICES = (
    ('lt_500', 'Under $500 / month'),
    ('500_1000', '$500 – $1,000 / month'),
    ('1000_2500', '$1,000 – $2,500 / month'),
    ('2500_5000', '$2,500 – $5,000 / month'),
    ('5000_10000', '$5,000 – $10,000 / month'),
    ('gt_10000', 'Over $10,000 / month'),
    ('prefer_not_to_say', 'Prefer not to say'),
)

# --- Religion ---------------------------------------------------------------
RELIGION_CHOICES = (
    ('christianity', 'Christianity'),
    ('islam', 'Islam'),
    ('hinduism', 'Hinduism'),
    ('buddhism', 'Buddhism'),
    ('sikhism', 'Sikhism'),
    ('judaism', 'Judaism'),
    ('jainism', 'Jainism'),
    ('bahai', 'Bahá’í'),
    ('folk', 'Folk or traditional religion'),
    ('other', 'Other religion'),
    ('spiritual', 'Spiritual but not religious'),
    ('agnostic', 'Agnostic'),
    ('atheist', 'Atheist / no religion'),
    ('prefer_not_to_say', 'Prefer not to say'),
)

# --- Ethnicity (broad global groupings) -------------------------------------
ETHNICITY_CHOICES = (
    ('south_asian', 'South Asian'),
    ('east_asian', 'East Asian'),
    ('southeast_asian', 'Southeast Asian'),
    ('central_asian', 'Central Asian'),
    ('mena', 'Middle Eastern or North African'),
    ('black_african', 'Black or African'),
    ('white_european', 'White or European'),
    ('hispanic_latino', 'Hispanic or Latino'),
    ('indigenous', 'Indigenous or First Nations'),
    ('pacific_islander', 'Pacific Islander'),
    ('multiracial', 'Multiracial or mixed'),
    ('other', 'Other'),
    ('prefer_not_to_say', 'Prefer not to say'),
)


def _valid_values(choices):
    return {value for value, _ in choices}


LANGUAGE_VALUES = _valid_values(LANGUAGE_CHOICES)
INDUSTRY_VALUES = _valid_values(INDUSTRY_CHOICES)
INCOME_VALUES = _valid_values(INCOME_CHOICES)
RELIGION_VALUES = _valid_values(RELIGION_CHOICES)
ETHNICITY_VALUES = _valid_values(ETHNICITY_CHOICES)


# --- Regions / subdivisions (ISO 3166-2 via pycountry) ----------------------
def _subdivision_name(subdivision):
    return subdivision.name


@lru_cache(maxsize=1)
def subdivisions_by_country():
    """Map country alpha-2 code -> sorted list of ``(sub_code, name)``."""
    grouped = {}
    for sub in pycountry.subdivisions:
        grouped.setdefault(sub.country_code, []).append((sub.code, _subdivision_name(sub)))
    for country_code in grouped:
        grouped[country_code].sort(key=lambda pair: pair[1])
    return grouped


@lru_cache(maxsize=1)
def subdivision_choices():
    """Flat, country-qualified choices: ``(sub_code, 'Region, Country')``.

    Used by the eligibility targeting picker where a creator selects regions
    across any country, so each label is disambiguated by its country name.
    """
    labelled = []
    for country_code, subs in subdivisions_by_country().items():
        country = pycountry.countries.get(alpha_2=country_code)
        country_name = country.name if country else country_code
        for sub_code, name in subs:
            labelled.append((sub_code, f'{name}, {country_name}'))
    labelled.sort(key=lambda pair: pair[1])
    return labelled


@lru_cache(maxsize=1)
def valid_subdivision_codes():
    return {code for code, _ in subdivision_choices()}
