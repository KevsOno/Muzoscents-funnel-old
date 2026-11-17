import { useEffect, useState } from 'react';

export interface Profile {
  id: string;
  role: string;
  full_name: string;
}

export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      // Use the central system's role and user info
      const role = localStorage.getItem('user_role') || 'admin';
      const name = localStorage.getItem('user_profile_display') || 'User';
      setProfile({
        id: 'central-user',
        role: role,
        full_name: name,
      });
    }
    setLoading(false);
  }, []);

  return { profile, loading };
}

export function clearProfileCache() {}
