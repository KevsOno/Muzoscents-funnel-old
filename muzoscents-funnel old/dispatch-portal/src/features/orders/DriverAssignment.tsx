import { useEffect, useState } from 'react';
import { Truck } from 'lucide-react';
import { supabase, type Profile } from '../../lib/supabase';

interface Props {
  branchId: string;
  value: string | null;
  onChange: (driverId: string | null) => void;
  disabled?: boolean;
}

export function DriverAssignment({ branchId, value, onChange, disabled }: Props) {
  const [drivers, setDrivers] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      // Fetch all active drivers in the branch, then keep anyone who is
      // available OR is the currently-assigned driver for this order.
      const { data, error } = await supabase
        .from('profiles')
        .select('id,user_id,email,full_name,phone,role,branch_id,driver_status,is_active')
        .eq('branch_id', branchId)
        .eq('role', 'driver')
        .eq('is_active', true)
        .order('full_name');
      if (cancelled) return;
      const all = error ? [] : ((data as Profile[]) ?? []);
      setDrivers(all.filter((d) => d.driver_status === 'available' || d.id === value));
      setLoading(false);
    };

    void load();

    const channel = supabase
      .channel(`drivers-avail-${branchId}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'profiles', filter: `branch_id=eq.${branchId}` },
        (payload) => {
          const p = payload.new as Profile;
          if (p.role !== 'driver') return;
          setDrivers((prev) => {
            const without = prev.filter((d) => d.id !== p.id);
            const keep = p.driver_status === 'available' && p.is_active;
            // Always keep the currently-selected driver visible.
            if (keep || p.id === value) return [...without, p];
            return without;
          });
        },
      )
      .subscribe();

    return () => { cancelled = true; supabase.removeChannel(channel); };
  }, [branchId, value]);

  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
        <Truck className="h-3.5 w-3.5" /> Assign driver (manual)
      </label>
      <select
        className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled || loading}
      >
        <option value="">{loading ? 'Loading drivers…' : 'Unassigned'}</option>
        {drivers.map((d) => (
          <option key={d.id} value={d.id}>
            {d.full_name || d.email}
            {d.id === value && d.driver_status !== 'available' ? ' (currently assigned)' : ''}
          </option>
        ))}
      </select>
      {!loading && drivers.filter((d) => d.driver_status === 'available').length === 0 && (
        <p className="text-xs text-amber-600">No available drivers in this branch.</p>
      )}
    </div>
  );
}
