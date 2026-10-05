import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import EnrollmentPage from './EnrollmentPage';
import * as enrollment from '../../lib/enrollment';
import { ApiError } from '../../lib/apiClient';

afterEach(() => vi.restoreAllMocks());

function renderPage(path = '/enroll') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <EnrollmentPage />
    </MemoryRouter>,
  );
}

const pinflInput = () => screen.getByLabelText(/JSHSHIR/) as HTMLInputElement;

describe('EnrollmentPage — hujjat bilan aniqlash', () => {
  it('guruh kodi maydoni yo‘q', () => {
    renderPage();
    expect(screen.queryByLabelText(/Guruh kodi/)).toBeNull();
  });

  it("JSHSHIR qat'iy 14 raqam bo'lishi talab qilinadi", () => {
    renderPage();
    expect(pinflInput().minLength).toBe(14);
    expect(pinflInput().maxLength).toBe(14);
  });
});

describe('EnrollmentPage — xabarlar', () => {
  it("serverning inglizcha 422 xabari ekranga chiqmaydi", async () => {
    vi.spyOn(enrollment, 'lookupPerson').mockRejectedValue(new ApiError(422, 'value is not a valid integer'));
    renderPage();

    fireEvent.change(pinflInput(), { target: { value: '30302654150047' } });
    fireEvent.click(screen.getByRole('button', { name: /Davom etish/ }));

    expect(await screen.findByText(/So'rovni bajarib bo'lmadi/)).toBeInTheDocument();
    expect(screen.queryByText(/valid integer/)).toBeNull();
  });

  it("404 da server matni ko'rsatiladi va o'zini qo'shish taklif qilinadi", async () => {
    vi.spyOn(enrollment, 'lookupPerson').mockRejectedValue(
      new ApiError(404, "Ma'lumot topilmadi yoki kod noto'g'ri"),
    );
    renderPage();

    fireEvent.change(pinflInput(), { target: { value: '30302654150047' } });
    fireEvent.click(screen.getByRole('button', { name: /Davom etish/ }));

    expect(await screen.findByText("Ma'lumot topilmadi yoki kod noto'g'ri")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /o'zimni qo'shish/ })).toBeInTheDocument();
  });
});

describe('EnrollmentPage — holatni tozalash', () => {
  it("qayta urinishda oldingi odamning holati qolmaydi", async () => {
    vi.spyOn(enrollment, 'lookupPerson').mockResolvedValue({
      recordId: '1',
      fullName: 'Aliyev Vali',
      typeLabel: 'Talaba',
      groupOrPosition: '301-guruh',
      alreadyEnrolled: false,
    });
    renderPage();

    fireEvent.change(pinflInput(), { target: { value: '30302654150047' } });
    fireEvent.click(screen.getByRole('button', { name: /Davom etish/ }));

    expect(await screen.findByText('Aliyev Vali')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Boshqa ma'lumot bilan qayta urinish/ }));

    await waitFor(() => expect(screen.queryByText('Aliyev Vali')).toBeNull());
    expect(pinflInput()).toBeInTheDocument();
  });
});
