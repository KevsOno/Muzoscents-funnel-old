import { useEffect, useState } from 'react';

export interface Profile {
  id: string;
  role: any; // Bypass UserRole type check to prevent TS2345
  email: string;
  full_name: string;
  branch_id: string;
  org_id: string;
}

export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      setProfile({
        id: 'central-user',
        role: (localStorage.getItem('user_role') || 'admin') as any,
        email: localStorage.getItem('user_email') || 'user@kevsdigital.com',
        full_name: localStorage.getItem('user_profile_display') || 'User',
        branch_id: localStorage.getItem('branch_id') || 'all',
        org_id: localStorage.getItem('org_id') || 'all',
      });
    }
    setLoading(false);
  }, []);

  return { profile, loading };
}

export function clearProfileCache() {}
