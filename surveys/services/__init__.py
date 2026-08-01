"""Draft mutation API for surveys.

Every function here takes the caller's expected revision and raises
``StaleVersionError`` when the draft has moved on, so concurrent builder tabs
cannot silently overwrite each other. The submodules group these by capability;
this package is their public surface.
"""
from .drafting import DEFAULT_SURVEY_TITLE, StaleVersionError, discard_empty_drafts
from .questions import (
    add_question,
    delete_question,
    duplicate_question,
    move_question,
    reorder_question,
    update_question,
)
from .rules import (
    add_branch_rule,
    delete_branch_rule,
    set_response_collection,
    update_eligibility,
    update_response_limit,
)
from .sections import add_section, delete_section, move_section, update_section


__all__ = [
    'DEFAULT_SURVEY_TITLE',
    'StaleVersionError',
    'add_branch_rule',
    'add_question',
    'add_section',
    'delete_branch_rule',
    'delete_question',
    'delete_section',
    'discard_empty_drafts',
    'duplicate_question',
    'move_question',
    'move_section',
    'reorder_question',
    'set_response_collection',
    'update_eligibility',
    'update_question',
    'update_response_limit',
    'update_section',
]
