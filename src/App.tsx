import { Navigate, Route, Routes } from 'react-router-dom';
import PublicLayout from './layouts/PublicLayout';
import AdminLayout from './layouts/AdminLayout';
import RequireAuth from './components/RequireAuth';
import RequirePermission from './components/RequirePermission';
import MonitoringPage from './pages/public/MonitoringPage';
import EnrollmentPage from './pages/public/EnrollmentPage';
import LoginPage from './pages/admin/LoginPage';
import ResetPasswordPage from './pages/admin/ResetPasswordPage';
import DashboardPage from './pages/admin/DashboardPage';
import StudentsStaffPage from './pages/admin/StudentsStaffPage';
import OrgStructurePage from './pages/admin/OrgStructurePage';
import CamerasZonesPage from './pages/admin/CamerasZonesPage';
import AIModulesPage from './pages/admin/AIModulesPage';
import UsersRolesPage from './pages/admin/UsersRolesPage';
import SystemLogPage from './pages/admin/SystemLogPage';
import ReportsPage from './pages/admin/ReportsPage';
import EventsPage from './pages/admin/EventsPage';
import AttendancePage from './pages/admin/AttendancePage';
import TeachingPage from './pages/admin/TeachingPage';

export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<MonitoringPage />} />
        <Route path="/royxatdan-otish" element={<EnrollmentPage />} />
      </Route>

      <Route path="/admin/login" element={<LoginPage />} />
      <Route path="/admin/reset-password" element={<ResetPasswordPage />} />

      <Route element={<RequireAuth />}>
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="events" element={<EventsPage />} />
          <Route path="students-staff" element={<StudentsStaffPage />} />
          <Route path="attendance" element={<AttendancePage />} />
          <Route path="teaching" element={<TeachingPage />} />
          <Route path="org-structure" element={<OrgStructurePage />} />
          <Route path="cameras" element={<CamerasZonesPage />} />
          <Route path="ai-modules" element={<AIModulesPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route element={<RequirePermission permission="manageRoles" />}>
            <Route path="users-roles" element={<UsersRolesPage />} />
          </Route>
          <Route element={<RequirePermission permission="systemSettings" />}>
            <Route path="system-log" element={<SystemLogPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
