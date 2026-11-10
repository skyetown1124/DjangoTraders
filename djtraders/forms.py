"""
The app's forms. A Form (or ModelForm) describes an HTML form's fields, validation
and rendering as a Python class instead of hand-written <input> tags.
CustomerEditForm is drawn by customer_edit.html with django-crispy-forms' crispy
tag (see INSTALLED_APPS and the CRISPY_* settings).

The customer form's fields show Django's three validation layers, each enforcing
the same rule a different way:
  - Browser (courtesy only): an HTML5 pattern=, required or min= attribute on the
    widget. It blocks an obviously bad value before a request is sent, but proves
    nothing, since DevTools or disabled JavaScript skips it.
  - Server (the real check): a clean_<field>() method, or the cross-field clean(),
    re-checks the rule and raises ValidationError. Nothing in the browser can
    bypass it.
  - Database (a backstop, when there is one): a column constraint such as
    max_length. Some rules, like no digits in a company name, have no database
    layer, so the form is the only thing enforcing them.
"""
import re
from datetime import timedelta

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Layout, Row
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Customer, Order, OrderDetail

# region [WHY] patterns shared by the browser and server layers
# Digits, spaces, parentheses and dashes, 7-20 characters: loose enough for
# "(206) 555-9857", tight enough to reject garbage. The widget's pattern= attribute
# and clean_phone() both use it, so the two can't drift apart.
# endregion
PHONE_PATTERN = r"[0-9()\-\s]{7,20}"

# region [CONCEPT] NO_DIGITS_PATTERN
# "[^0-9]*" means zero or more non-digit characters, so as a full match it says
# the whole string contains no digit. Shared the same way as PHONE_PATTERN.
# endregion
NO_DIGITS_PATTERN = r"[^0-9]*"


class CustomerEditForm(forms.ModelForm):
    """
    Edits every Customer field except customer_id (the primary key) and
    inactive_date (not part of this page).

    self.helper, a crispy FormHelper, is what the crispy tag reads to draw the
    grid and the Save button; without one crispy stacks the fields and adds no
    button. The Save and Cancel buttons are hand-written HTML because crispy's own
    Submit objects render a plain <input>, which can't hold an icon.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Browser layer: pattern= repeats PHONE_PATTERN, and title= is the tooltip
        # browsers show on a mismatch.
        self.fields["phone"].widget.attrs.update({
            "pattern": PHONE_PATTERN,
            "title": "Digits, spaces, parentheses, and dashes only (7-20 characters).",
        })
        # The no-digits fields have no database constraint behind them either.
        self.fields["company_name"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a company name.",
        })
        self.fields["city"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a city name.",
        })
        # The model allows a blank contact_name; required=True makes the form insist,
        # in the browser (required attribute) and on the server.
        self.fields["contact_name"].required = True
        self.helper = FormHelper()
        # A real id on the <form>, so ValidateCustomerEditForm (customers.js) can
        # find it; crispy renders none by default.
        self.helper.form_id = "customer-edit-form"
        # The field grid: Row and Column are crispy layout objects, each Column a
        # Bootstrap col-md-* width.
        self.helper.layout = Layout(
            Row(
                Column("company_name", css_class="col-md-6"),
                Column("contact_name", css_class="col-md-6"),
            ),
            Row(
                Column("contact_title", css_class="col-md-6"),
                Column("phone", css_class="col-md-6"),
            ),
            Row(
                Column("fax", css_class="col-md-6"),
                Column("password", css_class="col-md-6"),
            ),
            Row(
                Column("address", css_class="col-md-8"),
                Column("city", css_class="col-md-4"),
            ),
            Row(
                Column("region", css_class="col-md-4"),
                Column("postal_code", css_class="col-md-4"),
                Column("country", css_class="col-md-4"),
            ),
            HTML(
                """
                <div class="d-flex gap-2 mt-3 justify-content-end">
                    <button type="submit" class="btn dt-btn-primary-customer dt-hover-shadow" title="Save changes">
                        <i class="fa-solid fa-floppy-disk me-1 dt-icon-success"></i>Save
                    </button>
                    <div class="dt-link-wrap btn dt-btn-secondary-customer dt-hover-shadow">
                        {% if new_customer %}
                            <a href="{% url 'djtraders:customer_list' %}" title="Cancel -- nothing has been saved yet">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% else %}
                            <a href="{% url 'djtraders:customer_detail' customer.customer_id %}" title="Cancel and discard changes">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% endif %}
                    </div>
                </div>
                """
            ),
        )

    class Meta:
        model = Customer
        fields = [
            "company_name",
            "contact_name",
            "contact_title",
            "address",
            "city",
            "region",
            "postal_code",
            "country",
            "phone",
            "fax",
            "password",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=True),
        }

    def clean_phone(self):
        """
        Server layer for phone. Django calls clean_<field>() after the field's own
        type and length checks pass; this hand-written business rule raises
        ValidationError. phone is optional, so a blank value skips the pattern check.
        It runs even when the browser's pattern= was bypassed (curl, DevTools).
        """
        phone = self.cleaned_data.get("phone", "")
        if phone and not re.fullmatch(PHONE_PATTERN, phone):
            raise ValidationError(
                "Enter a valid phone number (digits, spaces, parentheses, "
                "and dashes only, 7-20 characters)."
            )
        return phone

    def clean_company_name(self):
        """Server layer: no digits. company_name is required, and Django checks that before this runs."""
        name = self.cleaned_data.get("company_name", "")
        if not re.fullmatch(NO_DIGITS_PATTERN, name):
            raise ValidationError("Company name can't contain numbers.")
        return name

    def clean_city(self):
        """Server layer: no digits. city is optional, so a blank value skips the check, as in clean_phone."""
        city = self.cleaned_data.get("city", "")
        if city and not re.fullmatch(NO_DIGITS_PATTERN, city):
            raise ValidationError("City can't contain numbers.")
        return city


class OrderDetailForm(forms.ModelForm):
    """
    Adds one line item (product, quantity, discount) to the cart. Only those three
    are collected; unit_price comes from the product's current price, not the form.

    discount_percent is a plain form field, not a model field, because the units
    differ: a customer types a percentage ("10") while OrderDetail.discount stores
    a fraction (0.10). The view (order_add_line) divides by 100 once validation
    passes.

    Up to 10% is accepted from anyone; only a cart an employee is driving
    (employee_initiated=True, from the session) may go as high as 100%. clean()
    checks quantity against the product's units_in_stock, a cross-field rule that
    needs product and quantity together. It is a courtesy check at add-to-cart time;
    order_commit (views/orders.py) re-checks against current stock before writing the
    order. category_id narrows the product choices to one category; it is optional
    because order_commit's error re-render builds this form without one.
    """
    discount_percent = forms.FloatField(
        required=False, initial=0, label="Discount %"
    )

    def __init__(self, *args, category_id=None, employee_initiated=False, **kwargs):
        super().__init__(*args, **kwargs)
        # clean_discount_percent reads this flag to pick the 10% or 100% ceiling.
        self.employee_initiated = employee_initiated

        # Only non-discontinued products are offered, like Product.search's default.
        products = self.fields["product"].queryset.filter(discontinued=0)
        if category_id:
            products = products.filter(category_id=category_id)
        self.fields["product"].queryset = products
        # region [CONCEPT] hidden product field
        # The autocomplete box (product_search_json) writes the chosen product's pk
        # into this hidden field. The queryset above is still the server-side gate: a
        # missing or discontinued pk fails validation whatever the browser sent.
        # endregion
        self.fields["product"].widget = forms.HiddenInput()
        self.fields["product"].error_messages["invalid_choice"] = (
            "Pick a product from the suggestions -- that one isn't available."
        )
        # Browser layer: min=1 blocks a zero or negative quantity before the request.
        self.fields["quantity"].widget.attrs.update({"min": 1, "class": "form-control"})
        # Starts at 1, the value the fresh card shows after each add.
        self.fields["quantity"].initial = 1
        # max= matches the ceiling clean_discount_percent enforces, so an employee's
        # cart shows a wider allowed range.
        self.fields["discount_percent"].widget.attrs.update({
            "min": 0,
            "max": 100 if employee_initiated else 10,
            "step": "0.01",
            "class": "form-control",
        })

    class Meta:
        model = OrderDetail
        fields = ["product", "quantity"]

    def clean_quantity(self):
        """Server layer: quantity must be at least 1."""
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        return quantity

    def clean_discount_percent(self):
        """Server layer for the discount ceiling (see the class docstring). A blank field counts as 0."""
        discount_percent = self.cleaned_data.get("discount_percent")
        if discount_percent is None:
            return 0.0
        if discount_percent < 0:
            raise ValidationError("Discount can't be negative.")
        ceiling = 100 if self.employee_initiated else 10
        if discount_percent > ceiling:
            raise ValidationError(
                f"Discount can't exceed {ceiling:g}% -- ask an employee to "
                f"place this order for a higher discount."
            )
        return discount_percent

    def clean(self):
        """
        Courtesy check: quantity can't exceed the product's units_in_stock. It needs
        two fields together, so it is clean() rather than clean_<field>(). A key
        missing from cleaned_data means that field already failed, and a NULL
        units_in_stock means there is no stock limit to check.
        """
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        quantity = cleaned_data.get("quantity")
        stock_known = product is not None and product.units_in_stock is not None
        if stock_known and quantity is not None and quantity > product.units_in_stock:
            self.add_error(
                "quantity",
                f"Only {product.units_in_stock} of {product.product_name} left in stock.",
            )
        return cleaned_data


class OrderCommitForm(forms.ModelForm):
    """
    Collects the employee, dates and shipping address when a cart becomes a placed
    Order. order_date is set by the view (order_commit, views/orders.py) to today,
    not picked.

    employee is required here even though the model column is nullable: "every
    placed order needs an employee" is a business rule, so the form is stricter than
    the column. Its dropdown shows full names because Employee has no __str__. The
    ship_* fields are editable and start from the customer's on-file address (the
    view passes it as initial=), so one order can ship elsewhere; name, address, city
    and country are required, region and postal code are not. required_date and
    shipped_date start two weeks and one week out (default_required_date,
    default_shipped_date) but stay editable.

    The form is used unbound (no instance=): order_commit calls
    form.save(commit=False) to build a new Order. A ModelForm creates or updates
    depending only on whether instance= was passed.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].required = True
        self.fields["employee"].empty_label = "Select an employee..."
        self.fields["employee"].queryset = self.fields["employee"].queryset.order_by(
            "last_name", "first_name"
        )
        self.fields["employee"].label_from_instance = (
            lambda employee: f"{employee.first_name} {employee.last_name}"
        )
        self.fields["employee"].widget.attrs.update({"class": "form-select"})

        # Required as a business rule, like employee: each of these columns is
        # nullable on Order itself.
        for field_name in ("ship_name", "ship_address", "ship_city", "ship_country"):
            self.fields[field_name].required = True
        for field_name in (
            "ship_name", "ship_address", "ship_city",
            "ship_region", "ship_postal_code", "ship_country",
        ):
            self.fields[field_name].widget.attrs.update({"class": "form-control"})

    class Meta:
        model = Order
        fields = [
            "employee",
            "required_date",
            "shipped_date",
            "ship_name",
            "ship_address",
            "ship_city",
            "ship_region",
            "ship_postal_code",
            "ship_country",
        ]
        widgets = {
            "required_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "shipped_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def clean(self):
        """
        Neither date may be before today: nothing in the database would stop a
        required or shipped date from being earlier than the order itself.
        """
        cleaned_data = super().clean()
        today = timezone.now().date()
        for field_name, label in (("required_date", "Required date"), ("shipped_date", "Ship-by date")):
            value = cleaned_data.get(field_name)
            if value is not None and value < today:
                self.add_error(field_name, f"{label} can't be before today's order date.")
        return cleaned_data


def default_required_date():
    """order_date (today, at commit) + 2 weeks -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=2)


def default_shipped_date():
    """order_date (today, at commit) + 1 week -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=1)
