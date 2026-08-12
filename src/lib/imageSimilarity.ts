const HASH_SIZE = 16;

function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = dataUrl;
  });
}

/**
 * Average-hash (aHash) perceptual hash: downscales the image to a small
 * grayscale grid and records which pixels are brighter than the mean.
 * Comparing two hashes via Hamming distance gives a lightweight, dependency-free
 * structural similarity score — not true face recognition, but a real,
 * deterministic comparison of the actual pixel data (not a random mock).
 */
async function averageHash(dataUrl: string): Promise<boolean[]> {
  const img = await loadImage(dataUrl);
  const canvas = document.createElement('canvas');
  canvas.width = HASH_SIZE;
  canvas.height = HASH_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D konteksti mavjud emas');

  ctx.drawImage(img, 0, 0, HASH_SIZE, HASH_SIZE);
  const { data } = ctx.getImageData(0, 0, HASH_SIZE, HASH_SIZE);

  const gray: number[] = [];
  for (let i = 0; i < data.length; i += 4) {
    gray.push(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]);
  }
  const avg = gray.reduce((a, b) => a + b, 0) / gray.length;
  return gray.map((v) => v > avg);
}

function hammingSimilarity(a: boolean[], b: boolean[]): number {
  let matches = 0;
  for (let i = 0; i < a.length; i++) {
    if (a[i] === b[i]) matches++;
  }
  return Math.round((matches / a.length) * 100);
}

export async function compareFaceImages(
  capturedFaceDataUrl: string,
  passportPhotoDataUrl: string,
): Promise<number> {
  const [hashA, hashB] = await Promise.all([
    averageHash(capturedFaceDataUrl),
    averageHash(passportPhotoDataUrl),
  ]);
  return hammingSimilarity(hashA, hashB);
}
