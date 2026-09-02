const MODULE_LABELS: Record<string, string> = {
  attendance: 'davomat',
  crowd: 'olomon',
  unauthorized: 'begona',
  sleep: 'uxlab qolish',
};

export function formatSecondsAgo(seconds: number | null | undefined): string {
  if (seconds == null) return "hali tahlil yo'q";
  if (seconds < 60) return `${seconds} soniya oldin`;
  const mins = Math.floor(seconds / 60);
  return `${mins} daqiqa oldin`;
}

export function formatModules(modules: string[]): string {
  if (!modules.length) return "modul yo'q";
  return modules.map((m) => MODULE_LABELS[m] ?? m).join(', ');
}
