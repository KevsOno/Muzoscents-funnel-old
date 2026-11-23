import { NavLink, Outlet } from 'react-router-dom';
import { useProfile } from '../lib/hooks/useProfile';
import { navFor } from '../lib/auth/roles';

export function AppShell() {
  const { profile } = useProfile();

  if (!profile) return <Outlet />;

  const items = navFor(profile.role);

  return (
    <div className="min-h-screen bg-slate-50 pb-16 sm:pb-0">
      {items.length > 1 && (
        <nav
          aria-label="Dispatch portal navigation"
          className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around gap-1 overflow-x-auto border-t border-slate-200 bg-white px-2 py-2 shadow-[0_-2px_8px_rgba(0,0,0,0.06)] sm:static sm:mx-auto sm:max-w-6xl sm:justify-start sm:border-t-0 sm:border-b sm:px-4 sm:shadow-none"
          style={{ paddingBottom: 'max(0.5rem, env(safe-area-inset-bottom))' }}
        >
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  'shrink-0 whitespace-nowrap rounded px-3 py-1.5 sm:py-1 text-xs font-medium',
                  isActive
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      )}

      <main className="mx-auto max-w-6xl">
        <Outlet />
      </main>
    </div>
  );
}
