import { NavLink, Outlet } from 'react-router-dom';
import { useProfile } from '../lib/hooks/useProfile';
import { navFor } from '../lib/auth/roles';

export function AppShell() {
  const { profile } = useProfile();

  if (!profile) return <Outlet />;

  const items = navFor(profile.role);

  return (
    <div className="min-h-screen bg-slate-50">
      {items.length > 1 && (
        <div className="mx-auto flex max-w-6xl items-center gap-1 overflow-x-auto border-b border-slate-200 bg-white px-4 py-2">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  'shrink-0 whitespace-nowrap rounded px-3 py-1 text-xs font-medium',
                  isActive
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}

      <main className="mx-auto max-w-6xl">
        <Outlet />
      </main>
    </div>
  );
}
