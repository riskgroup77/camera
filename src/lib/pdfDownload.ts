import { api, buildQuery } from './apiClient';
import { downloadBlob } from './download';

/**
 * Filtr natijasini PDF qilib yuklab olish (serverda yaratiladi:
 * camera-api/app/services/pdf_export.py). `params` — ekrandagi filtrlar.
 */
export async function downloadPdf(
  path: string,
  params: Record<string, string | number | undefined | null>,
  filename: string,
  token?: string | null,
): Promise<void> {
  const blob = await api.blob(`${path}${buildQuery(params)}`, token);
  downloadBlob(blob, filename.endsWith('.pdf') ? filename : `${filename}.pdf`);
}
