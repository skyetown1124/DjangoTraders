/**
 * Customers: client-side form validation and the dashboard's year dropdown.
 * Loaded by base.html after DjangoTraders.js.
 */

/**
 * Client-side validation for customer_edit.html, a courtesy on top of the
 * HTML5 pattern= attributes. The server-side checks in forms.py
 * (clean_phone, clean_company_name, clean_city) are the ones that enforce
 * the rules; the two patterns below are copied from forms.py by hand and
 * must be kept in sync, since a .js file can't import from Python.
 * @param {string} formId - selector for the form, e.g. "#customer-edit-form"
 */
function ValidateCustomerEditForm(formId) {
    const PHONE_PATTERN = /^[0-9()\-\s]{7,20}$/;
    const NO_DIGITS_PATTERN = /^[^0-9]*$/;

    // Shows or clears one field's error, using the same is-invalid and
    // .invalid-feedback classes Bootstrap uses for a server-side error.
    function setFieldError(fieldId, message) {
        const $field = $("#" + fieldId);
        let $feedback = $field.parent().find(".js-invalid-feedback").first();
        if ($feedback.length === 0) {
            $feedback = $("<div>").addClass("invalid-feedback js-invalid-feedback").insertAfter($field);
        }
        if (message) {
            $field.addClass("is-invalid");
            $feedback.text(message).show();
        } else {
            $field.removeClass("is-invalid");
            $feedback.hide();
        }
    }

    $(formId).on("submit", function (event) {
        let valid = true;

        // Blank values are skipped: company_name is already blocked by the
        // HTML5 required attribute, and phone and city are optional.
        const companyName = $("#id_company_name").val().trim();
        if (companyName && !NO_DIGITS_PATTERN.test(companyName)) {
            setFieldError("id_company_name", "Company name can't contain numbers.");
            valid = false;
        } else {
            setFieldError("id_company_name", null);
        }

        const phone = $("#id_phone").val().trim();
        if (phone && !PHONE_PATTERN.test(phone)) {
            setFieldError("id_phone", "Enter a valid phone number (digits, spaces, parentheses, and dashes only, 7-20 characters).");
            valid = false;
        } else {
            setFieldError("id_phone", null);
        }

        const city = $("#id_city").val().trim();
        if (city && !NO_DIGITS_PATTERN.test(city)) {
            setFieldError("id_city", "City can't contain numbers.");
            valid = false;
        } else {
            setFieldError("id_city", null);
        }

        if (!valid) {
            event.preventDefault();
        }
    });
}

/**
 * Customer dashboard: choosing a year loads that year's monthly chart
 * into #dashboard-monthly (and the latest year loads straight away).
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateYearDropdown($pane) {
    const $select = $pane.find("#dashboard-year");
    if ($select.length === 0) {
        return;
    }
    function loadMonthly() {
        $.get($select.data("url"), { year: $select.val() })
            .done(function (html) { $("#dashboard-monthly").html(html); })
            .fail(function () { $("#dashboard-monthly").text("Could not load the monthly chart."); });
    }
    $select.on("change", loadMonthly);
    loadMonthly();
}
