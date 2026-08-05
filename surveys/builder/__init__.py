"""The survey authoring workspace: the Questions, Settings and Preview tabs.

This is an internal package of the surveys app, not an app of its own. It may import downward from
the survey domain, but no survey domain module imports from here and nothing outside the surveys
app reaches into it: the workspace is reached through surveys/urls.py and through URL names.
"""
