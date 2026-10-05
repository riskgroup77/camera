import { compareFaceImages } from './imageSimilarity';
import { ApiError, api } from './apiClient';
import { isBackendConfigured } from './config';

export type FaceMatchMethod = 'local-ahash' | 'remote-api';

export interface FaceMatchResult {
  /** 0-100 oralig'ida moslik darajasi */
  confidence: number;
  matched: boolean;
  method: FaceMatchMethod;
  /** Masalan "yuz aniqlanmadi" kabi backend'dan kelgan aniq xato matni */
  message?: string;
}

const MATCH_THRESHOLD = 55;

async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return res.blob();
}

interface FaceCompareResponse {
  matched: boolean;
  confidence: number;
  similarity: number;
  facesDetectedA: number;
  facesDetectedB: number;
}

/**
 * Yuzlarni solishtirish xizmati. Backend ulangan bo'lsa POST /api/face/compare
 * orqali haqiqiy InsightFace/ArcFace biometrik taqqoslash bajariladi (512-o'lchamli
 * embedding'lar orasidagi kosinus o'xshashligi). Aks holda (demo rejim) mahalliy
 * average-hash (aHash) taqqoslash bilan davom etiladi.
 */
export async function compareFaces(
  capturedFaceDataUrl: string,
  passportPhotoDataUrl: string,
  token?: string | null,
): Promise<FaceMatchResult> {
  if (isBackendConfigured) {
    try {
      const [passportBlob, liveBlob] = await Promise.all([
        dataUrlToBlob(passportPhotoDataUrl),
        dataUrlToBlob(capturedFaceDataUrl),
      ]);
      const form = new FormData();
      // Maydon nomlari backend'ning FastAPI File() parametr nomlariga mos
      // bo'lishi shart (app/routers/face.py: image_a/image_b) — CamelModel
      // alias'i faqat Pydantic body'lariga tegishli, raw File() ga emas.
      form.append('image_a', passportBlob, 'passport.png');
      form.append('image_b', liveBlob, 'live.png');
      const result = await api.postForm<FaceCompareResponse>('/api/face/compare', form, token);
      return { confidence: result.confidence, matched: result.matched, method: 'remote-api' };
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        return { confidence: 0, matched: false, method: 'remote-api', message: err.message };
      }
      throw err;
    }
  }

  const confidence = await compareFaceImages(capturedFaceDataUrl, passportPhotoDataUrl);
  return {
    confidence,
    matched: confidence >= MATCH_THRESHOLD,
    method: 'local-ahash',
  };
}

export { MATCH_THRESHOLD };
