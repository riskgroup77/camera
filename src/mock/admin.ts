import type {
  AdminUser,
  AIModule,
  AIModuleGroup,
  AuditLogEntry,
  Building,
  CameraConfig,
  Faculty,
  Report,
  StudentGroup,
  StudentStaffRecord,
} from '../types';

export const dashboardStats = {
  totalStudents: { value: 4218, delta: '+34 bugun' },
  staff: { value: 342, delta: '+5 bugun' },
  activeCameras: { value: '86 / 90', delta: '96% bugun' },
  todayEvents: { value: 1247, delta: '+182 bugun' },
};

export const systemResources = { cpu: 42, ram: 68, disk: 55 };

export const AI_MODULE_GROUP_LABELS: Record<AIModuleGroup, string> = {
  A: 'Kirish-chiqish va hudud xavfsizligi',
  B: 'Davomat va shaxsni aniqlash',
  C: 'Forma va tashqi ko\'rinish',
  D: "Xulq-atvor va odob-axloq",
  E: "Ta'lim jarayoni sifati (dars monitoring)",
  F: 'Favqulodda holatlar',
};

// TT hujjat 3-bo'lim: 25 ta AI kriteriya (A-F toifalar). Faollik holati
// TT 12-bo'limdagi bosqichlar rejasiga mos: 1-bosqich (MVP) kriteriyalari
// hozir faol, qolganlari 2-3-bosqichda joriy etiladi.
export const aiModules: AIModule[] = [
  // A. Kirish-chiqish va hudud xavfsizligi
  { id: 'm1', code: 1, group: 'A', name: 'Notanish/begona shaxsni aniqlash', description: "Yuzni tanish (Face-ID) — xodimlar/talabalar bazasida yo'q shaxs binoga kirsa signal", method: 'YOLOv8-face + ArcFace, mahalliy GPU', accuracy: 97.8, threshold: 85, sensitivity: 'yuqori', cameraCount: 42, active: true },
  { id: 'm2', code: 2, group: 'A', name: 'Taqiqlangan zonaga kirish', description: 'Rentgen xonasi, laboratoriya, arxiv kabi cheklangan hududlarga ruxsatsiz kirish', method: 'Zona-poligon + object tracking (DeepSORT)', accuracy: 0, threshold: 80, sensitivity: 'yuqori', cameraCount: 0, active: false },
  { id: 'm3', code: 3, group: 'A', name: 'Notekis/kechki vaqtda kirish', description: 'Ish vaqtidan tashqari binoga kirish holatlari', method: 'Vaqt jadvali + kirish log tahlili (backend rule)', accuracy: 0, threshold: 70, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm4', code: 4, group: 'A', name: 'Egasiz qoldirilgan buyum', description: 'Koridor/hovlida uzoq vaqt qoldirilgan sumka, quti', method: 'Statik-obyekt aniqlash (background subtraction)', accuracy: 0, threshold: 75, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm5', code: 5, group: 'A', name: 'Olomon zichligi anomaliyasi', description: "Hovli yoki koridorda favqulodda to'planish", method: 'Crowd density estimation (CSRNet/YOLO-crowd)', accuracy: 92.8, threshold: 78, sensitivity: "o'rta", cameraCount: 12, active: true },

  // B. Davomat va shaxsni aniqlash
  { id: 'm6', code: 6, group: 'B', name: "Xodim/o'qituvchi davomati", description: "Ish boshlanish/tugash vaqtini yuz orqali avtomatik qayd etish", method: 'Face recognition + timestamp log', accuracy: 98.6, threshold: 88, sensitivity: 'yuqori', cameraCount: 30, active: true },
  { id: 'm7', code: 7, group: 'B', name: 'Talaba davomati', description: "Auditoriyaga kirish/darsda ishtirok etish avtomatik qaydi", method: 'Face recognition (sinf kamerasi)', accuracy: 99.2, threshold: 90, sensitivity: 'yuqori', cameraCount: 28, active: true },
  { id: 'm8', code: 8, group: 'B', name: 'Darsga kechikish', description: 'Belgilangan vaqtdan N daqiqa keyin kirish holati', method: 'Jadval bilan solishtirish (rule-based)', accuracy: 96.4, threshold: 85, sensitivity: "o'rta", cameraCount: 28, active: true },
  { id: 'm9', code: 9, group: 'B', name: 'Darsdan/ishdan erta ketish', description: 'Belgilangan tugash vaqtidan oldin xonani tark etish', method: 'Kirish-chiqish log tahlili', accuracy: 0, threshold: 80, sensitivity: "o'rta", cameraCount: 0, active: false },

  // C. Forma va tashqi ko'rinish
  { id: 'm10', code: 10, group: 'C', name: 'Oq xalat kiyilganligi', description: 'Tibbiy xodim/talabaning oq xalatda ekanligini aniqlash', method: 'Kiyim klassifikatsiyasi (fine-tuned YOLO/CLIP)', accuracy: 95.1, threshold: 82, sensitivity: 'yuqori', cameraCount: 34, active: true },
  { id: 'm11', code: 11, group: 'C', name: 'Bosh kiyim (kalpakcha) borligi', description: 'Amaliyot/laboratoriya xonalarida bosh kiyim taqilganligi', method: 'Object detection (head-region classifier)', accuracy: 93.7, threshold: 80, sensitivity: "o'rta", cameraCount: 18, active: true },
  { id: 'm12', code: 12, group: 'C', name: 'ID-badge taqilganligi', description: 'Xodim/talaba identifikatsiya kartochkasi ko\'rinishda ekanligi', method: 'Object detection (kichik obyekt, yaqin kamera talab qiladi)', accuracy: 0, threshold: 70, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm13', code: 13, group: 'C', name: "Qo'lqop/niqob (kerakli xonalarda)", description: 'Sanitariya talab qiladigan zonalarda SIZ mavjudligi', method: 'PPE detection modeli', accuracy: 0, threshold: 85, sensitivity: 'yuqori', cameraCount: 0, active: false },

  // D. Xulq-atvor va odob-axloq
  { id: 'm14', code: 14, group: 'D', name: 'Jang/nizolashish holati', description: 'Jismoniy toqnashuv yoki tajovuzkor harakatlar', method: 'Action recognition (pose + optical flow)', accuracy: 0, threshold: 88, sensitivity: 'yuqori', cameraCount: 0, active: false },
  { id: 'm15', code: 15, group: 'D', name: 'Chekish / elektron sigareta', description: 'Bino ichida yoki hovlida chekish holatlari', method: 'Obyekt + tutun/harakat klassifikatori', accuracy: 0, threshold: 75, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm16', code: 16, group: 'D', name: 'Imtihonda telefondan foydalanish', description: 'Nazorat ishi vaqtida ruxsatsiz qurilma ishlatish', method: 'Telefon obyekt detektsiyasi (YOLO)', accuracy: 0, threshold: 80, sensitivity: 'yuqori', cameraCount: 0, active: false },
  { id: 'm17', code: 17, group: 'D', name: 'Tartib-intizom buzilishi', description: 'Yugurish, xavfli harakat, koridorda shovqin-suron', method: 'Harakat anomaliyasi (pose estimation)', accuracy: 0, threshold: 65, sensitivity: 'past', cameraCount: 0, active: false },
  { id: 'm18', code: 18, group: 'D', name: 'Kiyim-bosh (dress code) umumiy', description: "Talabalarning institut nizomiga mos kiyingani", method: 'Kiyim klassifikatsiyasi', accuracy: 0, threshold: 70, sensitivity: "o'rta", cameraCount: 0, active: false },

  // E. Ta'lim jarayoni sifati (dars monitoring)
  { id: 'm19', code: 19, group: 'E', name: 'Talabaning darsga diqqati', description: "Boshning yo'nalishi, ko'z harakati, telefon bilan chalg'ishi asosida diqqat balli", method: 'Gaze estimation + pose (engagement score)', accuracy: 0, threshold: 60, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm20', code: 20, group: 'E', name: 'Talabaning uxlab qolishi', description: "Bosh pastga tushishi, ko'zlarning uzoq yopiq qolishi", method: 'Facial landmark + eye-closure (EAR) tahlili', accuracy: 0, threshold: 70, sensitivity: "o'rta", cameraCount: 0, active: false },
  { id: 'm21', code: 21, group: 'E', name: "O'qituvchi faolligi", description: "Doska oldida faol harakat, talabalar bilan interaktivlik vaqti", method: 'Pose tracking + zona-vaqt tahlili', accuracy: 0, threshold: 60, sensitivity: 'past', cameraCount: 0, active: false },
  { id: 'm22', code: 22, group: 'E', name: "O'qituvchining darsga aniq kelishi", description: 'Dars boshlanishi bilan xonada mavjudligi', method: 'Face recognition + jadval taqqoslash', accuracy: 0, threshold: 85, sensitivity: "o'rta", cameraCount: 0, active: false },

  // F. Favqulodda holatlar
  { id: 'm23', code: 23, group: 'F', name: 'Yong\'in / tutun aniqlash', description: 'Erta bosqichda tutun yoki alanga aniqlash', method: 'Fire/smoke detection CNN', accuracy: 0, threshold: 90, sensitivity: 'yuqori', cameraCount: 0, active: false },
  { id: 'm24', code: 24, group: 'F', name: 'Yiqilib tushish (fall detection)', description: 'Xodim yoki bemorning yiqilib qolishi', method: 'Pose-based fall detection', accuracy: 0, threshold: 85, sensitivity: 'yuqori', cameraCount: 0, active: false },
  { id: 'm25', code: 25, group: 'F', name: 'Hovlida transport harakati', description: 'Avtomobil/mototsikl piyodalar zonasida yoki taqiqlangan joyda', method: 'Vehicle detection + zona qoidasi', accuracy: 0, threshold: 75, sensitivity: "o'rta", cameraCount: 0, active: false },
];

const STUDENT_STAFF_SEED: StudentStaffRecord[] = [
  { id: 's1', fullName: 'Karimova Dildora Baxtiyorovna', type: 'talaba', faculty: 'Davolash ishi', groupOrPosition: '302-guruh, 3-kurs', biometricsStatus: 'tasdiqlangan', initials: 'KD' },
  { id: 's2', fullName: 'Rahimov Jasur Abdullayevich', type: 'talaba', faculty: 'Farmatsiya', groupOrPosition: '204-guruh, 2-kurs', biometricsStatus: 'kutilmoqda', initials: 'RJ' },
  { id: 's3', fullName: 'Toshmatova Feruza Hamidovna', type: 'xodim', faculty: 'Davolash ishi', groupOrPosition: 'Bosh hamshira', biometricsStatus: 'tasdiqlangan', initials: 'TF' },
  { id: 's4', fullName: 'Mirzayev Otabek Sobirovich', type: 'talaba', faculty: 'Pediatriya', groupOrPosition: '101-guruh, 1-kurs', biometricsStatus: 'yoq', initials: 'MO' },
  { id: 's5', fullName: 'Usmonova Hulkar Botiraliyevna', type: 'xodim', faculty: 'Davolash ishi', groupOrPosition: "O'qituvchi, Anatomiya", biometricsStatus: 'tasdiqlangan', initials: 'UH' },
  { id: 's6', fullName: 'Nazarov Sherzod Hamzayevich', type: 'talaba', faculty: 'Jamoat salomatligi', groupOrPosition: '403-guruh, 4-kurs', biometricsStatus: 'tasdiqlangan', initials: 'NS' },
];

const STUDENT_STAFF_FACULTIES_SEED = ['Davolash ishi', 'Farmatsiya', 'Pediatriya', 'Jamoat salomatligi'];
const EXTRA_FIRST_NAMES = ['Aziza', 'Bekzod', 'Dilnoza', 'Farrux', 'Gulnora', 'Ilhom', 'Jasmina', 'Kamron', 'Lola', 'Muzaffar', 'Nigora', 'Otabek'];
const EXTRA_LAST_NAMES = ['Yusupova', 'Qodirov', 'Saidova', 'Tursunov', 'Xolmatova', 'Ergashev', 'Nomozova', 'Sobirov'];
const EXTRA_GROUPS = ['101-guruh, 1-kurs', '204-guruh, 2-kurs', '302-guruh, 3-kurs', '403-guruh, 4-kurs', '506-guruh, 5-kurs'];
const EXTRA_BIOMETRICS: StudentStaffRecord['biometricsStatus'][] = ['tasdiqlangan', 'tasdiqlangan', 'kutilmoqda', 'yoq'];

// Pagination'ni real ro'yxat hajmida ko'rsatish uchun qo'shimcha generatsiya qilingan yozuvlar (demo maqsadida).
const generatedStudentsStaff: StudentStaffRecord[] = Array.from({ length: 28 }, (_, i) => {
  const n = i + 1;
  const first = EXTRA_FIRST_NAMES[n % EXTRA_FIRST_NAMES.length];
  const last = EXTRA_LAST_NAMES[n % EXTRA_LAST_NAMES.length];
  const faculty = STUDENT_STAFF_FACULTIES_SEED[n % STUDENT_STAFF_FACULTIES_SEED.length];
  const isStaff = n % 6 === 0;
  return {
    id: `s-gen-${n}`,
    fullName: `${last} ${first}`,
    type: isStaff ? 'xodim' : 'talaba',
    faculty,
    groupOrPosition: isStaff ? "O'qituvchi" : EXTRA_GROUPS[n % EXTRA_GROUPS.length],
    biometricsStatus: EXTRA_BIOMETRICS[n % EXTRA_BIOMETRICS.length],
    initials: `${last[0]}${first[0]}`,
  };
});

export const studentsStaff: StudentStaffRecord[] = [...STUDENT_STAFF_SEED, ...generatedStudentsStaff];

export const STUDENT_STAFF_FACULTIES = ['Davolash ishi', 'Farmatsiya', 'Pediatriya', 'Jamoat salomatligi'];

export const buildings: Building[] = [
  { id: 'b1', name: '1-Bino (Asosiy korpus)', cameraCount: 12 },
  { id: 'b2', name: '2-Bino (Klinika va Laboratoriya)', cameraCount: 18 },
  { id: 'b3', name: '3-Bino (Ma\'muriy bino)', cameraCount: 8 },
];

export const faculties: Faculty[] = [
  { id: 'f1', name: 'Davolash ishi', courseCount: 6, studentCount: 1520 },
  { id: 'f2', name: 'Farmatsiya', courseCount: 5, studentCount: 890 },
  { id: 'f3', name: 'Pediatriya', courseCount: 6, studentCount: 1140 },
  { id: 'f4', name: 'Jamoat salomatligi', courseCount: 4, studentCount: 668 },
];

export const studentGroups: StudentGroup[] = [
  { id: 'g1', name: '101-guruh', faculty: 'Davolash ishi', course: 1, studentCount: 28 },
  { id: 'g2', name: '204-guruh', faculty: 'Farmatsiya', course: 2, studentCount: 24 },
  { id: 'g3', name: '302-guruh', faculty: 'Davolash ishi', course: 3, studentCount: 26 },
  { id: 'g4', name: '403-guruh', faculty: 'Jamoat salomatligi', course: 4, studentCount: 22 },
  { id: 'g5', name: '506-guruh', faculty: 'Pediatriya', course: 5, studentCount: 20 },
  { id: 'g6', name: '605-guruh', faculty: 'Jamoat salomatligi', course: 6, studentCount: 18 },
];

export const cameraConfigs: CameraConfig[] = [
  { id: 'c1', name: 'Kirish eshigi kamerasi', ip: '192.168.1.101', port: 554, building: '1-Bino', zone: 'A-Zona (Kirish)', resolution: '1080p', fps: 25, status: 'faol', isReachable: true },
  { id: 'c2', name: 'Auditoriya 301 kamerasi', ip: '192.168.1.102', port: 554, building: '1-Bino', zone: "B-Zona (O'quv)", resolution: '720p', fps: 15, status: 'faol', isReachable: true },
  { id: 'c3', name: 'Klinika koridori', ip: '192.168.1.201', port: 554, building: '2-Bino', zone: 'C-Zona (Klinika)', resolution: '1080p', fps: null, status: 'tamirda', isReachable: false },
  { id: 'c4', name: 'Laboratoriya kirish', ip: '192.168.1.202', port: 554, building: '2-Bino', zone: 'C-Zona (Klinika)', resolution: '4K', fps: 25, status: 'faol', isReachable: true },
  { id: 'c5', name: 'Parking kamerasi', ip: '192.168.1.301', port: 554, building: '3-Bino', zone: 'D-Zona (Tashqi)', resolution: '1080p', fps: null, status: 'nofaol', isReachable: false },
  { id: 'c6', name: "Ma'muriyat zali", ip: '192.168.1.302', port: 554, building: '3-Bino', zone: 'E-Zona (Ma\'muriy)', resolution: '1080p', fps: 20, status: 'faol', isReachable: true },
];

export const adminUsers: AdminUser[] = [
  { id: 'u1', name: 'Jamshid Alimov', login: 'admin', initials: 'JA', lastLogin: 'Bugun, 09:14', role: 'Super Admin' },
  { id: 'u2', name: 'Nodira Yusupova', login: 'n.yusupova', initials: 'NY', lastLogin: 'Kecha, 17:42', role: 'Admin' },
  { id: 'u3', name: 'Behzod Karimov', login: 'operator', initials: 'BK', lastLogin: 'Bugun, 11:30', role: 'Admin' },
];

const AUDIT_LOG_SEED: AuditLogEntry[] = [
  { id: 'l1', timestamp: '2026-07-22 09:14:32', user: 'Jamshid Alimov', action: 'Tizimga kirish', module: 'Autentifikatsiya', status: 'muvaffaqiyatli', ip: '192.168.1.5' },
  { id: 'l2', timestamp: '2026-07-22 09:18:11', user: 'Jamshid Alimov', action: 'Yangi kamera qo\'shdi', module: 'Kameralar', status: 'muvaffaqiyatli', ip: '192.168.1.5' },
  { id: 'l3', timestamp: '2026-07-22 09:31:45', user: 'Nodira Yusupova', action: 'Tizimga kirish', module: 'Autentifikatsiya', status: 'muvaffaqiyatli', ip: '192.168.1.22' },
  { id: 'l4', timestamp: '2026-07-22 09:45:02', user: 'Nodira Yusupova', action: 'Talaba qo\'shdi', module: 'Talabalar', status: 'muvaffaqiyatli', ip: '192.168.1.22' },
  { id: 'l5', timestamp: '2026-07-22 10:02:17', user: 'Behzod Karimov', action: "Noto'g'ri parol", module: 'Autentifikatsiya', status: 'xatolik', ip: '192.168.1.31' },
  { id: 'l6', timestamp: '2026-07-22 10:15:38', user: 'Jamshid Alimov', action: "AI modul o'chirildi", module: 'AI Modullari', status: 'ogohlantirish', ip: '192.168.1.5' },
  { id: 'l7', timestamp: '2026-07-22 10:28:54', user: 'Nodira Yusupova', action: 'Kamera tahrirladi', module: 'Kameralar', status: 'muvaffaqiyatli', ip: '192.168.1.22' },
  { id: 'l8', timestamp: '2026-07-22 10:44:19', user: 'Jamshid Alimov', action: "Xodim o'chirildi", module: 'Talabalar', status: 'ogohlantirish', ip: '192.168.1.5' },
  { id: 'l9', timestamp: '2026-07-22 11:01:07', user: 'Behzod Karimov', action: 'Tizimga kirish', module: 'Autentifikatsiya', status: 'muvaffaqiyatli', ip: '192.168.1.31' },
  { id: 'l10', timestamp: '2026-07-22 11:30:22', user: 'Behzod Karimov', action: "Guruh qo'shdi", module: 'Tashkilot', status: 'muvaffaqiyatli', ip: '192.168.1.31' },
];

const AUDIT_ACTIONS = [
  'Tizimga kirish',
  'Kamera tahrirladi',
  "AI modul sozladi",
  "Hisobot yuklab oldi",
  'Talaba tahrirladi',
  "Parolni tiklashga urindi",
];
const AUDIT_USERS = ['Jamshid Alimov', 'Nodira Yusupova', 'Behzod Karimov'];
const AUDIT_MODULES = ['Autentifikatsiya', 'Kameralar', 'Talabalar', 'AI Modullari', 'Tashkilot'];
const AUDIT_STATUSES: AuditLogEntry['status'][] = ['muvaffaqiyatli', 'muvaffaqiyatli', 'muvaffaqiyatli', 'ogohlantirish', 'xatolik'];

// Pagination'ni real jurnal hajmida ko'rsatish uchun qo'shimcha generatsiya qilingan yozuvlar (demo maqsadida).
const generatedAuditLog: AuditLogEntry[] = Array.from({ length: 34 }, (_, i) => {
  const n = i + 1;
  const hour = String(8 + (n % 10)).padStart(2, '0');
  const min = String((n * 7) % 60).padStart(2, '0');
  return {
    id: `l-gen-${n}`,
    timestamp: `2026-07-2${1 - Math.floor(n / 34)} ${hour}:${min}:00`,
    user: AUDIT_USERS[n % AUDIT_USERS.length],
    action: AUDIT_ACTIONS[n % AUDIT_ACTIONS.length],
    module: AUDIT_MODULES[n % AUDIT_MODULES.length],
    status: AUDIT_STATUSES[n % AUDIT_STATUSES.length],
    ip: `192.168.1.${10 + (n % 240)}`,
  };
});

export const auditLog: AuditLogEntry[] = [...AUDIT_LOG_SEED, ...generatedAuditLog];

export const reports: Report[] = [
  {
    id: 'r1',
    period: 'Kunlik',
    periodLabel: '2026-07-30',
    generatedAt: '2026-07-30 23:05',
    source: 'llm',
    summary: "Davomat 96.4%, 1 ta begona shaxs signali (yolg'on ijobiy), forma buzilishi 3 holat.",
    body: "30-iyul kuni institut bo'yicha umumiy davomat 96.4% ni tashkil etdi (4218 nafardan 4066 nafar). Xodim/o'qituvchi davomati moduli 2 ta kechikish holatini qayd etdi (Farmatsiya fakulteti, 09:12 va 09:18). Forma nazorati bo'yicha 3 ta oq xalat kiyilmagan holat aniqlandi, barchasi Klinik baza binosida — bo'lim mudiriga xabar yuborildi. Begona shaxs aniqlash moduli 1 marta signal berdi (Kirish eshigi kamerasi, 14:32), tekshiruv natijasida bu yetkazib beruvchi xodimi ekanligi aniqlandi (yolg'on ijobiy). Olomon zichligi anomaliyasi qayd etilmadi. Tizim 42 ta faol kamera bo'yicha 24/7 rejimda barqaror ishladi, o'rtacha signal kechikishi 2.8 soniya.",
    stats: [
      { label: 'Umumiy davomat', value: '96.4%' },
      { label: 'AI signallar', value: '7' },
      { label: "Yolg'on ijobiy", value: '1' },
      { label: "O'rtacha kechikish", value: '2.8s' },
    ],
  },
  {
    id: 'r2',
    period: 'Haftalik',
    periodLabel: '2026-07-21 — 2026-07-27',
    generatedAt: '2026-07-27 22:40',
    source: 'llm',
    summary: 'Haftalik davomat trendi barqaror (95-97% oralig\'ida), forma buzilishlari 12% ga kamaydi.',
    body: "21-27 iyul oralig'idagi hafta davomida institut davomat ko'rsatkichi 95.1% dan 97.2% gacha o'zgardi, o'rtacha 96.2%. Dushanba va payshanba kunlari eng yuqori kechikish darajasi qayd etildi (mos ravishda 14 va 11 holat), bu jadval bilan solishtirilganda birinchi darsning ertaligi bilan bog'liq bo'lishi mumkin. Forma nazorati bo'yicha buzilishlar soni o'tgan haftaga nisbatan 12% ga kamaydi (31 dan 27 holatga), bu bo'lim mudirlariga yuborilgan avtomatik eslatmalar samara berayotganini ko'rsatadi. Xavfsizlik bo'yicha jiddiy hodisa qayd etilmadi. Tizim ishonchliligi (uptime) hafta davomida 99.4% ni tashkil etdi.",
    stats: [
      { label: "O'rtacha davomat", value: '96.2%' },
      { label: 'Jami AI signallar', value: '58' },
      { label: 'Forma buzilishi', value: '27 (-12%)' },
      { label: 'Uptime', value: '99.4%' },
    ],
  },
  {
    id: 'r3',
    period: 'Kunlik',
    periodLabel: '2026-07-29',
    generatedAt: '2026-07-29 23:02',
    source: 'llm',
    summary: 'Davomat 95.8%, xavfsizlik hodisalari qayd etilmadi.',
    body: "29-iyul kuni davomat 95.8% (4218 dan 4041 nafar). Kechikish holatlari — 9 ta, barchasi 5 daqiqadan kam. Forma nazorati bo'yicha 1 ta bosh kiyim (kalpakcha) yo'qligi holati aniqlandi (Laboratoriya-2, 2-korpus). Begona shaxs yoki xavfsizlik zonasi buzilishi qayd etilmadi. Olomon zichligi normal darajada.",
    stats: [
      { label: 'Umumiy davomat', value: '95.8%' },
      { label: 'AI signallar', value: '10' },
      { label: "Yolg'on ijobiy", value: '0' },
      { label: "O'rtacha kechikish", value: '3.1s' },
    ],
  },
  {
    id: 'r4',
    period: 'Oylik',
    periodLabel: '2026-06',
    generatedAt: '2026-07-01 08:00',
    source: 'rule',
    summary: "Iyun oyi statistik xulosasi — qoida-asosida avtomatik generatsiya qilindi.",
    body: "Iyun oyi davomida tizim 30 kunlik uzluksiz monitoringni amalga oshirdi. Oylik o'rtacha davomat 94.7% ni tashkil etdi. Jami 1140 ta AI signal qayd etildi, shundan 82% forma/davomat toifasiga, 18% xavfsizlik toifasiga tegishli. Tizim uptime 99.1%.",
    stats: [
      { label: "O'rtacha davomat", value: '94.7%' },
      { label: 'Jami signallar', value: '1140' },
      { label: 'Uptime', value: '99.1%' },
      { label: 'Faol kameralar', value: '42/50' },
    ],
  },
];
