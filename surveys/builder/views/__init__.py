"""Views behind the authoring workspace.

The submodules group these by what the creator is editing; this package is their public surface.
"""
from .branching import question_branch_add, question_branch_delete
from .questions import (
    question_add,
    question_delete,
    question_duplicate,
    question_move,
    question_reorder,
    question_update,
)
from .sections import section_add, section_delete, section_move, section_update
from .settings import (
    survey_banner_update,
    survey_builder_header_update,
    survey_edit,
    survey_rename,
    survey_response_collection,
)
from .workspace import survey_builder, survey_preview


__all__ = [
    'question_add',
    'question_branch_add',
    'question_branch_delete',
    'question_delete',
    'question_duplicate',
    'question_move',
    'question_reorder',
    'question_update',
    'section_add',
    'section_delete',
    'section_move',
    'section_update',
    'survey_banner_update',
    'survey_builder',
    'survey_builder_header_update',
    'survey_edit',
    'survey_preview',
    'survey_rename',
    'survey_response_collection',
]
