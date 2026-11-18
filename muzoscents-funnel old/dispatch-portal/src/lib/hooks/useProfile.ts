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
          // Fallback: decode the JWT from localStorage if Supabase auth fails
          const token = localStorage.getItem('access_token');
          if (token) {
            try {
              const payload = JSON.parse(atob(token.split('.')[1]));
              if (payload.sub) {
                if (!cancelled) {
                  console.log('DEBUG PROFILE:', profileData);
            setProfile({
                    id: payload.sub,
                    role: localStorage.getItem('user_role') || 'admin',
                    email: localStorage.getItem('user_email') || 'user@kevsdigital.com',
                    full_name: localStorage.getItem('user_profile_display') || 'User',
                    branch_id: localStorage.getItem('branch_id') || null,
                    org_id: localStorage.getItem('org_id') || '',
                  });
                  setLoading(false);
                }
                return;
              }
            } catch (e) {
              console.error('Failed to decode JWT', e);
            }
          }
          if (!cancelled) setLoading(false);
          return;
        }

        // Fetch the profile row from the database using the real UUID
        const { data: profileData, error: profileError } = await supabase
          .from('profiles')
          .select('*')
          .eq('id', user.id)
          .maybeSingle();

        if (!cancelled) {
          if (profileError || !profileData) {
            // Fallback to auth metadata if profile row is missing
            console.log('DEBUG PROFILE:', profileData);
            setProfile({
              id: user.id,
              role: user.user_metadata?.role || 'admin',
              email: user.email || '',
              full_name: user.user_metadata?.full_name || user.email || 'User',
              branch_id: null,
              org_id: user.user_metadata?.org_id || '',
            });
          } else {
            console.log('DEBUG PROFILE:', profileData);
            setProfile({
              id: profileData.id,
              role: profileData.role || 'admin',
              email: profileData.email || user.email || '',
              full_name: profileData.full_name || user.email || 'User',
              branch_id: profileData.branch_id || null,
              org_id: profileData.org_id || '',
            });
          }
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
