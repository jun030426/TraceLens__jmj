export function listPage<T>(items: T[], requested: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const page = Math.max(0, Math.min(requested, pages - 1));
  return { page, pages, items: items.slice(page * size, (page + 1) * size) };
}

export function matchesSearch(query: string, ...values: (string | undefined)[]) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const text = values.join(" ").toLocaleLowerCase();
  return words.every(word => text.includes(word));
}
