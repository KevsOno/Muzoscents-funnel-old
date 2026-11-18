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
        const { data: { user }, error: authError } = await supabase.auth.getUser();
        
        if (authError || !user) {
          if (!cancelled) setLoading(false);
          return;
        }

        // 1. Fetch the profile row
        const { data: profileData } = await supabase
          .from('profiles')
          .select('*')
          .eq('id', user.id)
          .maybeSingle();

        // 2. Fetch the org_members row for the org_id
        const { data: orgData } = await supabase
          .from('org_members')
          .select('org_id, role')
          .eq('user_id', user.id)
          .maybeSingle();

        if (!cancelled) {
          // Fallbacks in case things are missing
          const finalRole = orgData?.role || profileData?.role || user.user_metadata?.role || 'customer';
          const finalOrgId = orgData?.org_id || user.user_metadata?.org_id || localStorage.getItem('org_id') || '';

          console.log('DEBUG PROFILE:', { profileData, orgData, finalRole, finalOrgId });

          setProfile({
            id: user.id,
            role: finalRole,
            email: profileData?.email || user.email || '',
            full_name: profileData?.full_name || user.user_metadata?.full_name || 'User',
            branch_id: profileData?.branch_id || null,
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

export function clearProfileCache() {}
