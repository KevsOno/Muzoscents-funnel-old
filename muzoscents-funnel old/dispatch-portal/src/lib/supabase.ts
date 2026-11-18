import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// Restore the session into Supabase so auth.uid() works in RPCs
const token = localStorage.getItem('access_token');
const refresh = localStorage.getItem('refresh_token');
if (token && refresh) {
  supabase.auth.setSession({
    access_token: token,
    refresh_token: refresh
  }).catch((err) => console.warn("Failed to set Supabase session:", err));
}
