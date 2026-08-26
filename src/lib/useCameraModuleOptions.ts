import { useCallback, useEffect, useState } from 'react';
import { api } from './apiClient';
import { useAuth } from './auth';
import type { CameraModuleOption } from '../types';

/** Module checklist for camera admins — uses manageCameras-scoped endpoint. */
export function useCameraModuleOptions() {
  const { token } = useAuth();
  const [modules, setModules] = useState<CameraModuleOption[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    if (!token) return;
    setLoading(true);
    api
      .get<CameraModuleOption[]>('/api/cameras/module-options', token)
      .then(setModules)
      .catch(() => setModules([]))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { modules, loading, reload };
}
