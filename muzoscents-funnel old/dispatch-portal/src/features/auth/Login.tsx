import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../../lib/supabase';
import { useProfile } from '../../lib/hooks/useProfile';

type Mode = 'password' | 'magic';

function homeFor(role: string): string {
  switch (role) {
    case 'master':                return '/admin';
    case 'branch_manager':
    case 'fulfillment_officer':   return '/dashboard';
    case 'driver':                return '/driver';
    default:                      return '/login';
  }
}

export function Login() {
  const navigate = useNavigate();
  const { profile, loading } = useProfile();

  const [mode, setMode] = useState<Mode>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Once a profile is available (after password sign-in OR returning from a
  // magic-link click), bounce off /login to the right home for this role.
  useEffect(() => {
    if (loading || !profile) return;
    navigate(homeFor(profile.role), { replace: true });
  }, [loading, profile, navigate]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);

    const normalizedEmail = email.trim().toLowerCase();

    if (mode === 'password') {
      const { error } = await supabase.auth.signInWithPassword({
        email: normalizedEmail,
        password,
      });
      setBusy(false);
      if (error) setErr(error.message);
      // success → useProfile picks up the new session, effect above navigates
      return;
    }

    const { error } = await supabase.auth.signInWithOtp({
      email: normalizedEmail,
      options: {
        shouldCreateUser: false,
        emailRedirectTo: window.location.origin + '/login',
      },
    });
    setBusy(false);
    if (error) setErr(error.message);
    else setSent(true);
  }

  function switchMode(next: Mode) {
    setMode(next);
    setErr(null);
    setSent(false);
  }

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading…</div>;

  return (
    <form onSubmit={submit} className="mx-auto mt-24 max-w-sm space-y-3 p-4">
      <h1 className="text-lg font-semibold">Staff sign in</h1>
      <p className="text-xs text-slate-500">
        Accounts are provisioned by invitation. Sign in with your work email and password.
      </p>

      {sent ? (
        <div className="rounded border border-green-300 bg-green-50 p-3 text-sm text-green-800">
          Check your inbox for a sign-in link.
        </div>
      ) : (
        <>
          <input
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />

          {mode === 'password' && (
            <input
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          )}

          {err && <div className="text-xs text-red-600">{err}</div>}

          <button
            className="w-full rounded bg-blue-600 py-2 text-sm font-medium text-white disabled:opacity-50"
            disabled={busy}
          >
            {busy
              ? mode === 'password' ? 'Signing in…' : 'Sending…'
              : mode === 'password' ? 'Sign in' : 'Send sign-in link'}
          </button>

          <button
            type="button"
            onClick={() => switchMode(mode === 'password' ? 'magic' : 'password')}
            className="w-full text-xs text-slate-500 underline"
          >
            {mode === 'password'
              ? 'Or send me a magic link instead'
              : 'Or sign in with a password instead'}
          </button>
        </>
      )}
    </form>
  );
}
