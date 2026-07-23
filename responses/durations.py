def duration_seconds(started_at, completed_at):
    """Return a non-negative response duration, or None for invalid timestamps."""
    if not completed_at:
        return None
    seconds = round((completed_at - started_at).total_seconds())
    return seconds if seconds >= 0 else None


def format_duration_seconds(seconds):
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes}m'
    if minutes:
        return f'{minutes}m {seconds}s'
    return f'{seconds}s'
