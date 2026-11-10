"""
Template context processors for the djtraders app -- functions Django
runs for every template render, adding whatever they return into every
template's context automatically (see settings.py's TEMPLATES
OPTIONS['context_processors'], where this module is registered).

This file could be named anything -- Django finds a context processor by
the full dotted path given in settings.py (e.g.
"djtraders.session_context.current_employee"), not by filename or
location, unlike models.py/admin.py/apps.py, which Django's app loading
looks for by that exact name. "context_processors.py" is Django's own
common convention for this (django.template.context_processors,
django.contrib.auth.context_processors), but session_context.py names
what these two functions actually do here: read who's logged in back out
of request.session.

current_employee reads "current_user" (an employee_id) back out of
request.session -- set by login_view (views/employees.py) on a successful login -- so
base.html's navbar can show who's logged in without every view having
to look it up and pass it in its own context by hand. current_customer
is the same idea for the customer-facing login, reading "customer_id"
(set by customer_login_view in views/customers.py). Only one of the two is ever set at
a time, since login_view/customer_login_view/supplier_login_view each clear all three keys on
landing.
"""
from .models import Customer, Employee, Supplier


def current_employee(request):
    """
    Looks up the Employee matching request.session["current_user"], if
    any employee is currently logged in. Returns {"current_employee": None}
    when nobody is logged in, so base.html can safely check
    {% if current_employee %} on every page, logged in or not.
    """
    employee_id = request.session.get("current_user")
    employee = Employee.objects.filter(pk=employee_id).first() if employee_id else None
    return {"current_employee": employee}


def current_customer(request):
    """
    Looks up the Customer matching request.session["customer_id"], if
    any customer is currently logged in. Returns {"current_customer": None}
    when nobody is logged in, so base.html can safely check
    {% if current_customer %} on every page, logged in or not -- same
    shape as current_employee above, for the customer-facing side.
    """
    customer_id = request.session.get("customer_id")
    customer = Customer.objects.filter(pk=customer_id).first() if customer_id else None
    return {"current_customer": customer}


def current_supplier(request):
    """
    Looks up the Supplier matching request.session["supplier_id"], if
    any supplier is currently logged in. Returns {"current_supplier": None}
    when nobody is, same shape as current_customer above, for the
    supplier-facing side.
    """
    supplier_id = request.session.get("supplier_id")
    supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id else None
    return {"current_supplier": supplier}
