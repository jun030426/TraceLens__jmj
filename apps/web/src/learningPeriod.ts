export type Period = { from: string; to: string };
export function initialPeriod(): Period {
  const to = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
  }).format(new Date());
  const date = new Date(`${to}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 29);
  return { from: date.toISOString().slice(0, 10), to };
}
export function periodQuery(period: Period) {
  return new URLSearchParams({ date_from: period.from, date_to: period.to });
}
