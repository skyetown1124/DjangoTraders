"""
Project-level views for DjangoTraders.

Unlike djtraders/views.py, this file isn't inside a Django *app* --
it's a small views.py living alongside the project's settings.py and
urls.py, for a single "site home page" that isn't part of any one
app's feature set. If more project-wide pages are needed later, this
is where they'd go too.

home also doubles as a manual, simulated "session clear": there's no
reliable way to detect a browser closing (see this project's own
Module 2 changelog, "A session outlives the server process"), so a
real POST -- not just visiting the page -- is what actually ends a
session. See home()'s own docstring below for the GET/POST mechanics.
"""
from django.shortcuts import redirect, render


def home(request):
    """
    Project home page -- links into the djtraders app's own home page;
    becomes the index for more apps as they're added.

    Also this project's "start a new session" action (see this file's
    module docstring): POST pops current_user/customer_id from the
    session and redirects back here. A GET shows an in-page confirm
    alert (home.html) if either session key is still set, and renders
    normally otherwise -- covering both an anonymous visit and landing
    back here right after that POST.
    """
    if request.method == "POST":
        request.session.pop("current_user", None)
        request.session.pop("customer_id", None)
        return redirect("home")

    confirm_logout = bool(
        request.session.get("current_user") or request.session.get("customer_id")
    )

    # "home.html" (no "djtraders/" prefix) is found via TEMPLATES['DIRS']
    # in settings.py, not via an app's own templates/ folder.
    return render(request, "home.html", {"confirm_logout": confirm_logout})
