import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  throw new Error('Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY');
}

export const supabase = createClient(url, anonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
  realtime: {
    params: { eventsPerSecond: 5 },
  },
});

// Row types mirroring the DB prompt. Kept light — expand as needed.
export type UserRole = 'master' | 'branch_manager' | 'fulfillment_officer' | 'driver';
export type OrderStatus =
  | 'pending' | 'confirmed' | 'picked' | 'dispatched'
  | 'in_transit' | 'delivered' | 'cancelled' | 'failed';
export type DriverStatus = 'available' | 'on_delivery' | 'offline';

export interface Profile {
  id: string;
  user_id: string | null;
  email: string;
  full_name: string | null;
  phone: string | null;
  role: UserRole;
  branch_id: string | null;
  driver_status: DriverStatus;
  is_active: boolean;
}

export interface Customer {
  id: string;
  name: string;
  phone: string;
  email: string | null;
  address: string | null;
}

export interface Product {
  id: string;
  branch_id: string;
  sku: string | null;
  name: string;
  price: number;
}

export interface OrderRow {
  id: string;
  branch_id: string;
  customer_id: string;
  assigned_driver_id: string | null;
  status: OrderStatus;
  tracking_code: string;
  dispatch_cost: number | null;
  delivery_address: string;
  created_at: string;
  updated_at: string;
}
