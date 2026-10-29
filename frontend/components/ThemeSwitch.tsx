"use client";

import { useEffect, useState } from "react";
import { Icon, type IconName } from "./Icon";

type Theme = "light" | "dark" | "auto";

const OPTIONS: { key: Theme; label: string; icon: IconName }[] = [
  { key: "light", label: "Light", icon: "sun" },
  { key: "dark", label: "Dark", icon: "moon" },
  { key: "auto", label: "Match device", icon: "monitor" },
];

/** Light / Dark / Auto. The choice is kept in localStorage and applied as <html data-theme>. */
export default function ThemeSwitch({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    try {
      setTheme((localStorage.getItem("wf-theme") as Theme) || "light");
    } catch {}
  }, []);

  const choose = (t: Theme) => {
    setTheme(t);
    if (t === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
    try {
      localStorage.setItem("wf-theme", t);
    } catch {}
  };

  return (
    <div className={`theme-switch ${className}`} role="group" aria-label="Colour theme">
      {OPTIONS.map((o) => (
        <button key={o.key} type="button" aria-pressed={theme === o.key} onClick={() => choose(o.key)} title={o.label} aria-label={o.label}>
          <Icon name={o.icon} size={15} />
        </button>
      ))}
    </div>
  );
}
