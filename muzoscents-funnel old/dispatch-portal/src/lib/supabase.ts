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

// ── Types (re-exported for use across the app) ─────────────────────────

export type UserRole =
  | 'owner'
  | 'admin'
  | 'inventory_manager'
  | 'sales_rep'
  | 'finance'
  | 'logistics'
  | 'driver'
  | 'support'
  | 'customer';

export interface Profile {
  id: string;
  user_id?: string;
  email: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  phone?: string;
  role: UserRole;
  branch_id?: string | null;
  org_id?: string | null;
  driver_status?: string;
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface OrderRow {
  id: string;
  org_id: string;
  branch_id?: string;
  receipt_number?: string;
  customer_id?: string;
  customer_name?: string;
  customer_phone?: string;
  customer_email?: string;
  shipping_address?: string;
  shipping_status?: 'pending' | 'processing' | 'shipped' | 'delivered' | 'picked' | 'in_transit';
  payment_status?: string;
  status?: string;
  total_amount?: number;
  delivery_fee?: number;
  driver_id?: string | null;
  driver?: Profile;
  sale_items?: any[];
  created_at: string;
  updated_at?: string;
}

export interface Customer {
  id: string;
  org_id: string;
  email?: string;
  phone?: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  address?: string;
  created_at?: string;
}

export interface Product {
  id: number;
  org_id: string;
  item_code: string;
  description: string;
  price_naira: number;
  cost_price_naira?: number;
  current_qty?: number;
  product_group?: string;
  image_url?: string;
  created_at?: string;
}


// ── Dispatch portal: inject the KDS auth token so Supabase RPCs see auth.uid() ──
(() => {
  try {
    const _kds_access = localStorage.getItem('access_token');
    const _kds_refresh = localStorage.getItem('refresh_token');
    if (_kds_access && _kds_refresh) {
      supabase.auth.setSession({
        access_token: _kds_access,
        refresh_token: _kds_refresh,
      }).catch((err) => console.warn('[kds] Failed to set Supabase session:', err));
    }
  } catch (_) { /* ignore */ }
})();
