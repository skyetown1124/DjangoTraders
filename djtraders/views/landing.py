"""The app's home page."""

from django.shortcuts import render


def home(request):
    """
    The djtraders landing page. It has no data of its own and needs no login:
    home.html decides what to show from current_employee, current_customer and
    current_supplier (session_context.py).
    """
    return render(request, "djtraders/home.html")
