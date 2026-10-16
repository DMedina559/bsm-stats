/* Apply BSM appearance before first paint; storage is optional. */
"use strict";
(() => {
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: light)");
  let preferences = { mode: "system", density: "comfort" };
  try {
    const stored = JSON.parse(localStorage.getItem("bsm-stats-appearance"));
    if (["system", "dark", "light"].includes(stored?.mode))
      preferences.mode = stored.mode;
    if (["comfort", "compact"].includes(stored?.density))
      preferences.density = stored.density;
  } catch {
    /* Sandboxed/private browsing can deny storage. */
  }
  function apply() {
    root.dataset.mode =
      preferences.mode === "system"
        ? system.matches
          ? "light"
          : "dark"
        : preferences.mode;
    root.dataset.density = preferences.density;
  }
  apply();
  system.addEventListener("change", apply);
  document.addEventListener("DOMContentLoaded", () => {
    for (const name of ["mode", "density"]) {
      const control = document.getElementById(name);
      control.value = preferences[name];
      control.addEventListener("change", () => {
        preferences[name] = control.value;
        apply();
        try {
          localStorage.setItem(
            "bsm-stats-appearance",
            JSON.stringify(preferences),
          );
        } catch {
          /* Optional persistence. */
        }
      });
    }
  });
})();
