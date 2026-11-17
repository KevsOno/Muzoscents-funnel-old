// src/features/dashboard/MasterDashboard.tsx
import { useState } from 'react';
import { useProfile } from '../../lib/hooks/useProfile';
import { useRealtimeOrders } from '../../lib/realtime/useRealtimeOrders';
import { BranchSwitcher } from './BranchSwitcher';
import { BranchDashboard } from './BranchDashboard';
import { AnalyticsView } from './AnalyticsView';

function MasterGlobalView({
  branchId,
  setBranchId,
}: {
  branchId: string | null;
  setBranchId: (id: string | null) => void;
}) {
  const { orders } = useRealtimeOrders(null);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Global dashboard</h1>
        <BranchSwitcher value={branchId} onChange={setBranchId} />
      </header>

      <section>
        <h2 className="mb-2 text-sm font-medium text-slate-600">All orders</h2>
        <ul className="divide-y rounded border border-slate-200 bg-white">
          {orders.map((o) => (
            <li key={o.id} className="px-3 py-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{o.delivery_address}</span>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs uppercase">
                  {o.status}
                </span>
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                <code>{o.tracking_code}</code> · branch {o.branch_id.slice(0, 8)}
              </div>
            </li>
          ))}
          {orders.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-slate-400">No orders.</li>
          )}
        </ul>
      </section>

      <AnalyticsView />
    </div>
  );
}

export function MasterDashboard() {
  const { profile } = useProfile();
  const [branchId, setBranchId] = useState<string | null>(null);

  if (profile?.role !== 'master') return null;

  if (branchId) {
    return (
      <div>
        <div className="p-4">
          <BranchSwitcher value={branchId} onChange={setBranchId} />
        </div>
        <BranchDashboard />
      </div>
    );
  }

  return <MasterGlobalView branchId={branchId} setBranchId={setBranchId} />;
}
