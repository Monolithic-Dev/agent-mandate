// Light, dark or follow the system. The choice is a per-browser convenience, so it lives in
// localStorage (guarded: storage can be unavailable) and is applied as data-theme on <html>.

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "mandate.theme";

function read(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  window.dispatchEvent(new Event("mandate-theme"));
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() =>
    typeof window === "undefined" ? "system" : read(),
  );

  useEffect(() => apply(choice), [choice]);

  const set = useCallback((next: ThemeChoice) => {
    try {
      if (next === "system") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, next);
    } catch {
      // Storage unavailable (private window, blocked site data): the choice lasts this visit.
    }
    setChoice(next);
  }, []);

  return [choice, set];
}

/** Re-render when the theme changes, for things drawn outside CSS (the graph canvas). */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((n) => n + 1);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    window.addEventListener("mandate-theme", bump);
    media?.addEventListener?.("change", bump);
    return () => {
      window.removeEventListener("mandate-theme", bump);
      media?.removeEventListener?.("change", bump);
    };
  }, []);
  return version;
}
