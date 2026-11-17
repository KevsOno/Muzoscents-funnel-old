
import { useEffect, useState } from 'react';
import { supabase, type Profile } from '../../lib/supabase';
import { useProfile } from '../../lib/hooks/useProfile';
import { useRealtimeOrders } from '../../lib/realtime/useRealtimeOrders';
import { MapWrapper } from '../../components/map/MapWrapper';
import type { MapMarker } from '../../components/map/types';
import { DriverAssignment } from '../orders/DriverAssignment';
import { AnalyticsView } from './AnalyticsView';

interface Loc { driver_id: string; lat: number; lng: number; updated_at: string; }

export function BranchDashboard() {
  const { profile } = useProfile();
  const branchId = profile?.branch_id ?? null;
  const { orders } = useRealtimeOrders(branchId);
  const [locs, setLocs] = useState<Record<string, Loc>>({});
  const [drivers, setDrivers] = useState<Profile[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);

  // Live driver positions for this branch.
  useEffect(() => {
    if (!branchId) return;
    let cancelled = false;

    const load = async () => {
      const { data } = await supabase
        .from('driver_locations')
        .select('driver_id,lat,lng,updated_at')
        .eq('branch_id', branchId);
      if (cancelled) return;
      const map: Record<string, Loc> = {};
      for (const row of (data as Loc[]) ?? []) map[row.driver_id] = row;
      setLocs(map);
    };
    void load();

    const ch = supabase
      .channel(`locs-${branchId}`)
      .on('postgres_changes',
        { event: '*', schema: 'public', table: 'driver_locations', filter: `branch_id=eq.${branchId}` },
        (payload) => {
          const row = payload.new as Loc;
          setLocs((prev) => ({ ...prev, [row.driver_id]: row }));
        })
      .subscribe();

    return () => { cancelled = true; supabase.removeChannel(ch); };
  }, [branchId]);

  // Driver directory (for names on markers).
  useEffect(() => {
    if (!branchId) return;
    (async () => {
      const { data } = await supabase
        .from('profiles')
        .select('id,user_id,email,full_name,phone,role,branch_id,driver_status,is_active')
        .eq('branch_id', branchId)
        .eq('role', 'driver');
      setDrivers((data as Profile[]) ?? []);
    })();
  }, [branchId]);

  const markers: MapMarker[] = Object.values(locs).map((l) => {
    const d = drivers.find((x) => x.id === l.driver_id);
    return {
      id: l.driver_id,
      lat: l.lat,
      lng: l.lng,
      label: d?.full_name || d?.email || 'Driver',
      tone: d?.driver_status === 'available' ? 'success' : 'primary',
    };
  });

  const selected = orders.find((o) => o.id === selectedOrderId) ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <h1 className="text-xl font-semibold">
        {profile?.role === 'branch_manager' ? 'Branch manager' : 'Fulfillment'} dashboard
      </h1>

      <section>
        <h2 className="mb-2 text-sm font-medium text-slate-600">Live fleet map</h2>
        <MapWrapper markers={markers} zoom={12} className="h-80 w-full rounded-lg" />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div>
          <h2 className="mb-2 text-sm font-medium text-slate-600">Live orders</h2>
          <ul className="divide-y rounded border border-slate-200 bg-white">
            {orders.map((o) => (
              <li key={o.id}
                  className={`cursor-pointer px-3 py-2 text-sm hover:bg-slate-50 ${
                    selectedOrderId === o.id ? 'bg-blue-50' : ''
                  }`}
                  onClick={() => setSelectedOrderId(o.id)}>
                <div className="flex items-center justify-between">
                  <span className="font-medium">{o.delivery_address}</span>
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs uppercase">{o.status}</span>
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  <code>{o.tracking_code}</code>
                </div>
              </li>
            ))}
            {orders.length === 0 && <li className="px-3 py-6 text-center text-sm text-slate-400">No orders yet.</li>}
          </ul>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-medium text-slate-600">Order detail</h2>
          {selected && branchId ? (
            <div className="space-y-3 rounded border border-slate-200 bg-white p-3">
              <div className="text-sm"><b>Address:</b> {selected.delivery_address}</div>
              <div className="text-sm"><b>Status:</b> {selected.status}</div>
              <div className="text-sm"><b>Tracking code:</b> <code>{selected.tracking_code}</code></div>
              <DriverAssignment
                branchId={branchId}
                value={selected.assigned_driver_id}
                onChange={async (driverId) => {
                  await supabase.from('orders')
                    .update({ assigned_driver_id: driverId })
                    .eq('id', selected.id);
                }}
              />
            </div>
          ) : (
            <p className="text-sm text-slate-400">Select an order to view details.</p>
          )}
        </div>
      </section>

      <AnalyticsView />
    </div>
  );
}
