"""
Who may see or do what. The session holds one login at a time: "current_user"
(an employee id), "customer_id" or "supplier_id"; each login page clears the
other two. Each helper below checks one rule, so a view calls it first and turns
the visitor away (a redirect or a 403) instead of repeating the session checks.
"""

from django.shortcuts import redirect

from ..models import Employee


def own_customer_redirect(request, customer_id):
    """
    Sends a logged-in customer to their own page when customer_id is someone
    else's. Returns None for an employee, a visitor, or a customer already on
    their own page. customer_list passes customer_id=None, so any logged-in
    customer is sent to their own page.
    """
    logged_in_customer_id = request.session.get("customer_id")
    if logged_in_customer_id and logged_in_customer_id != customer_id:
        return redirect("djtraders:customer_detail", customer_id=logged_in_customer_id)
    return None


def customer_access_denied(request, customer_id):
    """
    True unless the session is an employee (who may act for any customer) or
    that customer's own login. Gates customer_edit and every cart view.
    """
    if request.session.get("current_user"):
        return False
    return request.session.get("customer_id") != customer_id


def order_access_denied(request, order):
    """
    True unless the session is an employee or the order's own customer. An order
    whose customer was deleted (customer_id is None) is open to employees only.
    """
    if request.session.get("current_user"):
        return False
    if order.customer_id is None:
        return True
    return order.customer_id != request.session.get("customer_id")


def customer_tab_denied(request, customer_id):
    """
    True when a logged-in customer asks for someone else's tab. Employees and
    visitors may view any customer's page, so only a different customer is refused.
    """
    logged_in_customer_id = request.session.get("customer_id")
    return bool(logged_in_customer_id) and logged_in_customer_id != customer_id


def supplier_access_denied(request, supplier_id):
    """
    True unless the session is that supplier or an employee. A supplier page
    shows what each product earns, so unlike a customer page it is closed to
    visitors.
    """
    if request.session.get("current_user"):
        return False
    return request.session.get("supplier_id") != supplier_id


def employee_access_denied(request, employee_id):
    """
    True unless a logged-in employee is viewing their own page, or is a manager
    (an employee other employees report to, Employee.is_manager). A manager may
    open any employee's page; visitors, customers and suppliers are turned away.
    """
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return True
    if viewer_id == employee_id:
        return False
    viewer = Employee.objects.filter(pk=viewer_id).first()
    return viewer is None or not viewer.is_manager


def customer_dashboard_denied(request, customer_id):
    """
    Assignment 3: the customer Dashboard tab and its chart views. True unless
    the session is an employee or that customer's own login. Stricter than
    customer_tab_denied, which lets a visitor who is not logged in see any
    customer's tabs: the dashboard shows what a customer spends, so a visitor
    is refused too.
    """
    if request.session.get("current_user"):
        return False
    return request.session.get("customer_id") != customer_id
