"""Form widgets shared by more than one app."""
from django import forms


class PillCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """Renders a multi-select as tappable pills instead of a checkbox column."""

    template_name = 'core/widgets/pill_select.html'
