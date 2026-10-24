// The dashboard's appearance, light, dark or the same as the computer, which each
// browser remembers for itself.
export const appearances = ["light", "dark", "system"] as const;
export type Appearance = (typeof appearances)[number];
export const APPEARANCE_KEY = "undercover-appearance";

export function storedAppearance(): Appearance {
  const stored = localStorage.getItem(APPEARANCE_KEY);
  return appearances.find((appearance) => appearance === stored) ?? "system";
}

// Sets the page's colors, which follow the computer's when no theme is set.
export function applyAppearance(appearance: Appearance) {
  localStorage.setItem(APPEARANCE_KEY, appearance);
  if (appearance === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = appearance;
}
