import { api } from './apiClient';
import { isBackendConfigured } from './config';

export interface UploadedFile {
  id: string;
  url: string;
  name: string;
}

/**
 * Fayl saqlash xizmati. Backend ulangan bo'lsa POST /api/uploads orqali
 * haqiqiy MinIO'ga (S3-mos) yuklanadi va doimiy presigned URL qaytadi.
 * Aks holda (demo rejim) mahalliy object URL bilan davom etiladi.
 */
export async function uploadFile(
  file: File | Blob,
  name = 'file',
  token?: string | null,
  prefix = 'misc',
): Promise<UploadedFile> {
  const filename = file instanceof File ? file.name : name;

  if (isBackendConfigured) {
    const form = new FormData();
    form.append('file', file, filename);
    return api.postForm<UploadedFile>(`/api/uploads?prefix=${encodeURIComponent(prefix)}`, form, token);
  }

  const url = URL.createObjectURL(file);
  return {
    id: `local-${Date.now()}-${Math.round(Math.random() * 1e6)}`,
    url,
    name: filename,
  };
}

/** Object URL bilan bog'liq xotirani bo'shatadi — komponent unmount bo'lganda chaqirilishi kerak. */
export function releaseUploadedFile(url: string) {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url);
}
