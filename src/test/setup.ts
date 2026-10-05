import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// To'liq to'plam parallel ishlaganda (100+ fayl) sahifalar sekinroq chiziladi —
// standart 1 s kutish ba'zan yetmay, testlar tasodifan yiqilardi.
configure({ asyncUtilTimeout: 4000 });
