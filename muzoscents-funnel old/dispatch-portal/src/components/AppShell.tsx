import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { supabase } from '../lib/supabase';
import { useProfile } from '../lib/hooks/useProfile';
import { navFor } from '../lib/auth/roles';

export function AppShell() {
  const { profile } = useProfile();
  const navigate = useNavigate();

  // AppShell is only mounted inside a gate that already guarantees a profile,
  // but belt-and-braces in case of a sign-out race.
  if (!profile) return <Outlet />;

  const items = navFor(profile.role);

  async function signOut() {
    await supabase.auth.signOut();
    navigate('/login', { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">LogiFlow</div>

          <nav className="flex flex-1 items-center gap-1">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    'rounded px-3 py-1.5 text-sm',
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

          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-xs font-medium text-slate-800">
                {profile.full_name ?? profile.email}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                {profile.role.replace('_', ' ')}
              </div>
            </div>
            <button
              onClick={signOut}
              className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-100"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl">
        <Outlet />
      </main>
    </div>
  );
}
