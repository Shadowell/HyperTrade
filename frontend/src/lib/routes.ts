import type { NavSection } from "../types";

export function activeSectionFromPath(pathname?: string): NavSection {
  const rawPath =
    pathname ?? (typeof window === "undefined" ? "/harness" : window.location.pathname);
  const segments = rawPath.split("/").filter(Boolean);
  const section = segments.at(-1) ?? "harness";

  if (section === "missions" || section === "portfolio") {
    return "missions";
  }
  if (
    section === "knowledge" ||
    section === "memory" ||
    section === "rag" ||
    section === "strategy"
  ) {
    return "knowledge";
  }
  if (section === "system" || section === "alerts" || section === "quality") {
    return "system";
  }
  return "harness";
}

export function sectionPath(section: NavSection): string {
  return section === "harness" ? "/harness" : `/harness/${section}`;
}
