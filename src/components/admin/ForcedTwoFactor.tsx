import { useEffect, useState } from 'react';
import { LogOut, ShieldAlert } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { TWO_FACTOR_REQUIRED_EVENT } from '../../lib/apiClient';
import { twoFactorApi } from '../../lib/twoFactorApi';
import { Button } from '../../ui';
import TwoFactorModal from './TwoFactorModal';

/**
 * Administratorlar uchun 2FA majburiy (camera-api/app/dependencies.py).
 *
 * Server 2FA'si yoqilmagan administratorga faqat kirish va 2FA sozlash
 * yo'llarini ochadi. Bu oyna shuni tushuntiradi va sozlashga olib boradi;
 * 2FA yoqilgach sahifa yangilanadi — barcha ma'lumot endi yuklanadi.
 */
export default function ForcedTwoFactor() {
  const { token, twoFactorRequired, logout } = useAuth();
  const [forced, setForced] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);

  useEffect(() => {
    const onRequired = () => setForced(true);
    window.addEventListener(TWO_FACTOR_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(TWO_FACTOR_REQUIRED_EVENT, onRequired);
  }, []);

  const show = Boolean(token) && (forced || twoFactorRequired);
  if (!show) return null;

  async function afterSetup() {
    setSetupOpen(false);
    try {
      const status = await twoFactorApi.status();
      if (status.enabled) window.location.reload();
    } catch {
      /* holatni olib bo'lmadi — oyna ochiq qoladi */
    }
  }

  // Sozlash oynasi ochiq bo'lsa — faqat u (Modal o'z qatlamida chiziladi).
  if (setupOpen) return <TwoFactorModal open onClose={afterSetup} />;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4" role="alertdialog" aria-modal="true" aria-labelledby="forced-2fa-title">
      <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 shadow-pop">
        <div className="mb-3 flex items-center gap-2">
          <ShieldAlert size={20} className="text-warning" aria-hidden="true" />
          <h2 id="forced-2fa-title" className="text-[16px] font-bold text-fg">
            Ikki bosqichli kirishni yoqing
          </h2>
        </div>
        <p className="text-[13px] leading-relaxed text-muted">
          Administrator hisoblari uchun ikki bosqichli kirish (2FA) majburiy. Telefoningizga Google Authenticator yoki
          shunga o‘xshash ilovani o‘rnating, QR-kodni skanerlang va 6 xonali kodni kiriting. Shundan keyin tizim to‘liq
          ochiladi.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => setSetupOpen(true)}>
            2FA ni yoqish
          </Button>
          <Button variant="ghost" icon={LogOut} onClick={logout}>
            Chiqish
          </Button>
        </div>
      </div>
    </div>
  );
}
