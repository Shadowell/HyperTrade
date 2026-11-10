import type { NavSection } from "../types";

export function activeSectionFromPath(): NavSection {
  if (typeof window === "undefined") {
    return "harness";
  }
  const section = window.location.pathname.split("/").filter(Boolean).at(-1) ?? "harness";
  if (
    section === "missions" ||
    section === "strategy" ||
    section === "portfolio" ||
    section === "alerts" ||
    section === "runs" ||
    section === "quality" ||
    section === "memory" ||
    section === "rag"
  ) {
    return section;
  }
  return "harness";
}

export function sectionPath(section: NavSection): string {
  return section === "harness" ? "/harness" : `/harness/${section}`;
}
