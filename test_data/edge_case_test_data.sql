-- Optional edge-case test data used for the Assignment 3 screenshots.
-- Not required to run the project. Running it twice is harmless (ON CONFLICT DO NOTHING).
--   * Supplier 30 "Piedmont Test Foods" with one product and one order (a supplier with very little data)
--   * Employee 10 "Avery Newhire" with one order (an employee with very few orders; password = birth year 2000)
--   * Customer NGSKL "A Test Customer" with no orders (password: pass)
-- Remove it again with the DELETE statements at the bottom.

INSERT INTO suppliers (supplier_id, company_name, contact_name, city, country, phone)
VALUES (30, 'Piedmont Test Foods', 'Test Contact', 'Greensboro', 'USA', '(336) 555-0100')
ON CONFLICT DO NOTHING;

INSERT INTO products (product_id, product_name, supplier_id, category_id, quantity_per_unit,
                      unit_price, units_in_stock, units_on_order, reorder_level, discontinued)
VALUES (78, 'Piedmont Sourwood Honey', 30, 2, '12 - 8 oz jars', 14, 40, 0, 10, 0)
ON CONFLICT DO NOTHING;

INSERT INTO employees (employee_id, last_name, first_name, title, birth_date, hire_date, reports_to, city, country)
VALUES (10, 'Newhire', 'Avery', 'Sales Representative', '2000-03-15', '2026-03-01', 5, 'Greensboro', 'USA')
ON CONFLICT DO NOTHING;

INSERT INTO customers (customer_id, company_name, contact_name, city, country, "Password")
VALUES ('NGSKL', 'A Test Customer', 'Test Contact', 'Greensboro', 'USA', 'pass')
ON CONFLICT DO NOTHING;

INSERT INTO orders (order_id, customer_id, employee_id, order_date, required_date, shipped_date,
                    ship_via, freight, ship_name, ship_city, ship_country)
VALUES (11078, 'CENTC', 10, '2026-04-14', '2026-04-28', '2026-04-18', 1, 12.5,
        'Centro comercial Moctezuma', 'México D.F.', 'Mexico')
ON CONFLICT DO NOTHING;

INSERT INTO order_details (order_id, product_id, unit_price, quantity, discount) VALUES
    (11078, 78, 14, 6, 0),
    (11078,  3, 10, 4, 0.05)
ON CONFLICT DO NOTHING;

-- To remove:
-- DELETE FROM order_details WHERE order_id = 11078;
-- DELETE FROM orders WHERE order_id = 11078;
-- DELETE FROM products WHERE product_id = 78;
-- DELETE FROM suppliers WHERE supplier_id = 30;
-- DELETE FROM employees WHERE employee_id = 10;
-- DELETE FROM customers WHERE customer_id = 'NGSKL';
