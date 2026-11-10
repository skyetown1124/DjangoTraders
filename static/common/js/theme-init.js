/*
    Dark mode, step 1 of 2 -- runs in <head>, BEFORE the page draws.

    Loaded (not deferred) from templates/common/base.html's <head> so the
    saved theme is applied before the body paints; loading it at the end
    of <body> with DjangoTraders.js would flash the light page first.

    The choice is a per-browser convenience, so it lives in localStorage
    under "dt-theme" ("light" or "dark"). Light is the default. Reading
    storage can throw (private windows, blocked site data), so it's in a
    try/catch and simply falls back to light.

    Bootstrap 5.3 switches its own components with data-bs-theme on
    <html>; the "dark" class is the hook DataTables' stylesheet uses.
    DjangoTraders.css redefines the project's --dt-* tokens under the same
    attribute. The toggle button and the chart theming are step 2, in
    DjangoTraders.js (the "Dark mode" region).
*/
(function () {
    var theme = "light";
    try {
        if (window.localStorage.getItem("dt-theme") === "dark") {
            theme = "dark";
        }
    } catch (e) {
        theme = "light";
    }
    document.documentElement.setAttribute("data-bs-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
})();
