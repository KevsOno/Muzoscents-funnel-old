import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useProfile } from '../lib/hooks/useProfile';
import { homeFor } from '../lib/auth/roles';

export function NotAuthorised() {
  const { profile } = useProfile();

  return (
    <div className="mx-auto mt-24 max-w-md space-y-4 p-6 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
        <ShieldAlert className="h-6 w-6 text-amber-700" />
      </div>

      <div className="space-y-1">
        <h1 className="text-lg font-semibold text-slate-900">Not authorised</h1>
        <p className="text-sm text-slate-500">
          Your account doesn&apos;t have access to this page.
        </p>
      </div>

      {profile && (
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Signed in as <span className="font-medium">{profile.full_name ?? profile.email}</span>
          <br />
          Role: <span className="font-medium capitalize">{profile.role.replace('_', ' ')}</span>
        </div>
      )}

      <div className="flex justify-center gap-2">
        {profile && (
          <Link
            to={homeFor(profile.role)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Go to my dashboard
          </Link>
        )}
        <Link
          to="/login"
          className="rounded border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
        >
          Switch account
        </Link>
      </div>
    </div>
  );
}
