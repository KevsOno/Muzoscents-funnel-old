import { useEffect, useState } from 'react';
import { supabase } from '../supabase';

export interface Profile {
  id: string;
  role: any;
  email: string;
  full_name: string;
  branch_id: string | null;
  org_id: string;
}

export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser();
        
        if (!user) {
          if (!cancelled) setLoading(false);
          return;
        }

        // Use limit(1) instead of maybeSingle() to avoid throwing if multiple orgs exist
        const [profileRes, orgRes] = await Promise.all([
          supabase.from('profiles').select('*').eq('id', user.id).limit(1),
          supabase.from('org_members').select('org_id, role').eq('user_id', user.id).limit(1)
        ]);

        if (!cancelled) {
          const p = profileRes.data?.[0];
          const o = orgRes.data?.[0];

          const finalRole = o?.role || p?.role || user.user_metadata?.role || 'customer';
          const finalOrgId = o?.org_id || user.user_metadata?.org_id || '';

          setProfile({
            id: user.id,
            role: finalRole,
            email: p?.email || user.email || '',
            full_name: p?.full_name || user.user_metadata?.full_name || 'User',
            branch_id: p?.branch_id || null,
            org_id: finalOrgId,
          });
          setLoading(false);
        }
      } catch (err) {
        console.error('Failed to load profile', err);
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => { cancelled = true; };
  }, []);

  return { profile, loading };
}
