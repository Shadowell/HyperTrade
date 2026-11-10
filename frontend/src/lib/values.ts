export function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(stringifyValue).join(", ");
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .slice(0, 4)
      .map(([key, item]) => `${key}=${stringifyValue(item)}`)
      .join(" / ");
  }
  return String(value);
}

export function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(stringifyValue).filter((item) => item.length > 0);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

export function summarizeRecord(value: Record<string, unknown> | undefined): string {
  if (!value) {
    return "n/a";
  }
  const entries = Object.entries(value).slice(0, 4);
  if (entries.length === 0) {
    return "n/a";
  }
  return entries.map(([key, item]) => `${key}=${stringifyValue(item)}`).join(" / ");
}

export function keyValueRows(value: unknown): Array<{ label: string; value: string }> {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const label = stringOrUndefined(item.label ?? item.name ?? item.key);
        if (!label) {
          return null;
        }
        return { label, value: stringifyValue(item.value ?? item.amount ?? item.metric ?? "") };
      })
      .filter((item): item is { label: string; value: string } => Boolean(item));
  }
  if (isRecord(value)) {
    return Object.entries(value).map(([label, item]) => ({
      label,
      value: stringifyValue(item)
    }));
  }
  return [];
}
