import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { Counts, GroupDetail, GroupStudent } from '../../lib/situationApi';

const student = (id: string, fullName: string, status: GroupStudent['status']): GroupStudent => ({
  id, fullName, photoUrl: null, initials: '', status, checkIn: null, checkOut: null, biometricsStatus: 'tasdiqlangan',
});

// 1 keldi, 1 kech, 1 ma'lumot yo'q, 1 dam olish → "Ma'lumot yo'q" plitkasi 2 ko'rsatadi.
const students = [
  student('a', 'Aliyev Anvar', 'keldi'),
  student('b', 'Botirova Barno', 'kech_keldi'),
  student('c', 'Choriyev Chori', 'malumot_yoq'),
  student('d', 'Davronov Davron', 'dam_olish'),
];

const totals: Counts = {
  total: 4, enrolled: 4, present: 2, late: 1, absent: 0, dayOff: 1, notYet: 0, noData: 1, rate: 100,
};

const baseDetail: GroupDetail = {
  date: '2026-09-20',
  isToday: true,
  group: { name: 'DI-2301', facultyId: 'f1', faculty: 'Davolash ishi', course: 1, totals },
  students,
  lessons: [],
  trend: [],
};

let detail: GroupDetail = baseDetail;

vi.mock('../../lib/situationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/situationApi')>();
  return { ...original, getGroup: vi.fn(async () => detail) };
});
vi.mock('../../lib/realtime', () => ({ useLiveAttendance: () => {} }));
vi.mock('../../components/students/StudentDrawer', () => ({ StudentDrawer: () => null }));
vi.mock('../../components/students/GroupEnrollDrawer', () => ({ GroupEnrollDrawer: () => null }));

import GroupPage from './GroupPage';

function renderPage(initial = '/talabalar/guruh/DI-2301') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/talabalar/guruh/:groupName" element={<GroupPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const tile = (label: string) => screen.getByRole('radio', { name: new RegExp(label) });

describe('Guruh sahifasi — holat plitkalari', () => {
  beforeEach(() => {
    localStorage.clear();
    detail = baseDetail;
  });

  it("«Ma'lumot yo'q» plitkasidagi son bosilgandan keyingi ro'yxat bilan bir xil", async () => {
    // Plitka noData + dayOff ni ko'rsatardi, filtr esa faqat malumot_yoq ni
    // olardi: "2" bosilganda setkada bitta talaba qolardi.
    renderPage();
    await waitFor(() => expect(screen.getByText('Aliyev Anvar')).toBeInTheDocument());
    const target = tile("Ma'lumot yo'q");
    expect(target).toHaveTextContent('2');

    fireEvent.click(target);
    await waitFor(() => expect(screen.queryByText('Aliyev Anvar')).not.toBeInTheDocument());
    expect(screen.getByText('Choriyev Chori')).toBeInTheDocument();
    expect(screen.getByText('Davronov Davron')).toBeInTheDocument();
    // Filtr yorlig'i ham "2 / 4" deb turadi.
    expect(screen.getByText(/Ma'lumot yo'q: 2 \/ 4/)).toBeInTheDocument();
  });

  it("qiymati 0 bo'lgan plitka bosilmaydi (bo'sh setka o'rniga)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Aliyev Anvar')).toBeInTheDocument());
    expect(tile('Kelmadi')).toBeDisabled();
    expect(tile('O‘z vaqtida')).toBeEnabled();
    expect(tile('Jami')).toBeEnabled();
  });

  it("holat filtri URL'da saqlanadi — chuqur havola bir xil chiziladi", async () => {
    renderPage('/talabalar/guruh/DI-2301?holat=kech_keldi');
    await waitFor(() => expect(screen.getByText('Botirova Barno')).toBeInTheDocument());
    expect(screen.queryByText('Aliyev Anvar')).not.toBeInTheDocument();
    expect(tile('Kech keldi')).toHaveAttribute('aria-checked', 'true');
  });
});

describe('Guruh sahifasi — qidiruv va tozalash', () => {
  beforeEach(() => {
    localStorage.clear();
    detail = baseDetail;
  });

  it("«Filtrni tozalash» holat filtrini ham, qidiruvni ham bir yo'la oladi", async () => {
    // Ilgari setQuery/setFilter/setFaceFilter ketma-ket chaqirilardi va
    // keyingisi eski parametrlardan boshlab oldingisining o'chirganini
    // qaytarib qo'yardi — holat filtri joyida qolib ketardi.
    renderPage('/talabalar/guruh/DI-2301?holat=keldi&qidiruv=zzz');
    await waitFor(() => expect(screen.getByText('Talaba topilmadi')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Filtrni tozalash' }));
    await waitFor(() => expect(screen.getByText('Aliyev Anvar')).toBeInTheDocument());
    expect(screen.getByText('Davronov Davron')).toBeInTheDocument();
    expect(tile('Jami')).toHaveAttribute('aria-checked', 'true');
  });

  it("qidiruv URL'da saqlanadi", async () => {
    renderPage('/talabalar/guruh/DI-2301?qidiruv=Botirova');
    await waitFor(() => expect(screen.getByText('Botirova Barno')).toBeInTheDocument());
    expect(screen.queryByText('Aliyev Anvar')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Talaba ismi…')).toHaveValue('Botirova');
  });

  it("kelmagan talabaning qatorida holat so'z bilan yoziladi", async () => {
    // Qator izohi («hali kelmadi», «kirdi») olib tashlandi — u holat
    // belgisini takrorlardi. Holat harfi yonidagi SO'Z esa qoladi: rang
    // yolg'iz ma'no tashimasin.
    detail = {
      ...baseDetail,
      students: [student('e', 'Eshonov Eshon', 'kutilmoqda'), student('f', 'Fayzullayev Fayz', 'kelmadi')],
    };
    renderPage();
    await waitFor(() => expect(screen.getByText('Eshonov Eshon')).toBeInTheDocument());
    expect(screen.getAllByText('Hali kelmagan').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Kelmadi').length).toBeGreaterThan(0);
  });
});
