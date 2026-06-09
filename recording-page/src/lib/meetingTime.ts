/**
 * Calculate seconds until a UTC datetime string
 * Returns negative if past
 */
export function secondsUntil(utcIso: string): number {
  return Math.floor((new Date(utcIso).getTime() - Date.now()) / 1000);
}

export function formatTime(utcIso: string, timeZone?: string): string {
  return new Date(utcIso).toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
}

export function formatDuration(startIso: string, endIso: string): string {
  const startMs = new Date(startIso).getTime();
  const endMs = new Date(endIso).getTime();
  const mins = Math.round((endMs - startMs) / 60000);
  return `${Math.floor(mins / 60)}시간 ${mins % 60}분`.replace("0시간 ", "");
}
