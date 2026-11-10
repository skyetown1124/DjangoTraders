"""
Reading the values a dashboard control sends (Assignment 3). Each new chart
view takes its year, "Show Top" or measure from the query string, and the
browser can send anything, so every value is checked against a fixed list of
what the control offers, the same rule as the provided views (for example
employee_team_chart). A value that is not on the list comes back as BAD, and
the view answers it with a 400 and a short message instead of crashing.
"""

BAD = object()


def read_year(value, years, allow_all=True):
    """
    None for "all" (when the control offers All years), the year as an int
    when it is one of years (the user's own order years), otherwise BAD.
    """
    if allow_all and value == "all":
        return None
    if not value or not value.isdigit():
        return BAD
    year = int(value)
    return year if year in years else BAD


def read_top(value, allowed=("5", "10", "all")):
    """None for "all", the number as an int for the other choices the Show Top radio buttons offer (5 or 10), otherwise BAD."""
    if value not in allowed:
        return BAD
    return None if value == "all" else int(value)


def read_choice(value, allowed):
    """value when it is one of allowed (a fixed list or dict of keys), otherwise BAD."""
    return value if value in allowed else BAD
