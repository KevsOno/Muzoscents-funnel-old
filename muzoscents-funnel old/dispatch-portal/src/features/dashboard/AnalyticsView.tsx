import { useEffect, useState } from 'react';
import { supabase } from '../../lib/supabase';
import { useProfile } from '../../lib/hooks/useProfile';
import { BranchSwitcher } from './BranchSwitcher';

interface Summary {
  branch_scope: string | null;
  orders_count: number;
  deliveries_completed: number;
  products_value: number;
  dispatch_cost_total: number;
  avg_dispatch_cost: number;
}

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export function AnalyticsView() {
  const { profile } = useProfile();
  const [start, setStart] = useState(todayISO(-30));
  const [end, setEnd] = useState(todayISO(0));
  const [branchId, setBranchId] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setErr(null);
    const { data, error } = await supabase.rpc('analytics_summary', {
      p_start_date: start,
      p_end_date: end,
      p_branch_id: profile?.role === 'master' ? branchId : null,
    });
    setLoading(false);
    if (error) { setErr(error.message); return; }
    setSummary((data as Summary[])?.[0] ?? null);
  }

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.role]);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-slate-600">Financial analytics</h2>

      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <label className="text-xs">
          <div className="text-slate-500">Start</div>
          <input type="date" className="rounded border border-slate-300 px-2 py-1 text-sm"
                 value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="text-xs">
          <div className="text-slate-500">End</div>
          <input type="date" className="rounded border border-slate-300 px-2 py-1 text-sm"
                 value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        {profile?.role === 'master' && (
          <label className="text-xs">
            <div className="text-slate-500">Branch</div>
            <BranchSwitcher value={branchId} onChange={setBranchId} />
          </label>
        )}
        <button onClick={run} disabled={loading}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {loading ? 'Running…' : 'Run'}
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Orders" value={summary.orders_count} />
          <Stat label="Deliveries completed" value={summary.deliveries_completed} />
          <Stat label="Products value" value={Number(summary.products_value).toFixed(2)} />
          <Stat label="Dispatch cost" value={Number(summary.dispatch_cost_total).toFixed(2)} />
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
