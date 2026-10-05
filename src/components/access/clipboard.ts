/** Matnni buferga nusxalash (eski brauzer va HTTP uchun zaxira yo'l bilan). */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Eski brauzer yoki HTTP (clipboard API faqat xavfsiz kontekstda).
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  }
}
