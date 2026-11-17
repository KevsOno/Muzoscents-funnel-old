import { useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase, type Profile } from '../supabase';

let cached: Profile | null = null;

async function fetchProfile(session: Session | null): Promise<Profile | null> {
  if (!session) return null;
  const { data, error } = await supabase
    .from('profiles')
    .select('id,user_id,email,full_name,phone,role,branch_id,driver_status,is_active')
    .eq('user_id', session.user.id)
    .maybeSingle();
  if (error || !data) return null;
  return data as Profile;
}

export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(cached);
  const [loading, setLoading] = useState(cached === null);

  useEffect(() => {
    let cancelled = false;

    async function apply(session: Session | null) {
      const next = await fetchProfile(session);
      if (cancelled) return;
      cached = next;
      setProfile(next);
      setLoading(false);
    }

    // Initial read
    void supabase.auth.getSession().then(({ data }) => {
      void apply(data.session);
    });

    // Live updates. Never call supabase.auth.* synchronously inside this
    // callback — it holds the auth lock and will deadlock. Use the
    // `session` argument that Supabase already resolved for us.
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        cached = null;
        setProfile(null);
        setLoading(false);
        return;
      }
      if (event === 'TOKEN_REFRESHED') return;
      void apply(session);
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  return { profile, loading };
}

export function clearProfileCache() {
  cached = null;
}
