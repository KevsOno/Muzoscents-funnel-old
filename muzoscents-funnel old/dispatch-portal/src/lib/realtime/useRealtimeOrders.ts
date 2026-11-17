import { useEffect, useState } from 'react';
import { supabase, type OrderRow } from '../supabase';

export function useRealtimeOrders(branchId: string | null) {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    // Unique per hook instance so two components asking for the same branch
    // don't collide on a shared channel (which triggers:
    // "cannot add postgres_changes callbacks ... after subscribe()").
    const instanceId = Math.random().toString(36).slice(2, 8);
    const channelName = `orders-${branchId ?? 'all'}-${instanceId}`;

    const load = async () => {
      let q = supabase
        .from('orders')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(200);
      if (branchId) q = q.eq('branch_id', branchId);
      const { data } = await q;
      if (!cancelled) {
        setOrders((data as OrderRow[]) ?? []);
        setLoading(false);
      }
    };
    void load();

    const filter = branchId ? `branch_id=eq.${branchId}` : undefined;
    const channel = supabase
      .channel(channelName)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'orders',
          ...(filter ? { filter } : {}),
        },
        (payload) => {
          setOrders((prev) => {
            if (payload.eventType === 'DELETE') {
              return prev.filter((o) => o.id !== (payload.old as OrderRow).id);
            }
            const next = payload.new as OrderRow;
            const without = prev.filter((o) => o.id !== next.id);
            return [next, ...without].sort((a, b) =>
              a.created_at < b.created_at ? 1 : -1,
            );
          });
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [branchId]);

  return { orders, loading };
}
