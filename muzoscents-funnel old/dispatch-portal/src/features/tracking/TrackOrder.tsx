import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { Package, MapPin, Truck, Clock } from 'lucide-react';
import { supabase } from '../../lib/supabase';
import { MapWrapper } from '../../components/map/MapWrapper';
import type { MapMarker } from '../../components/map/types';

interface TrackingPayload {
  tracking_code: string;
  status: string;
  delivery_address: string;
  pickup_branch: string;
  created_at: string;
  dispatched_at: string | null;
  delivered_at: string | null;
  driver_position: { lat: number; lng: number; updated_at: string } | null;
  items: { name: string; quantity: number; price: number }[];
}

const POLL_MS = 15_000;

export function TrackOrder() {
  const { tracking_code } = useParams<{ tracking_code: string }>();
  const [data, setData] = useState<TrackingPayload | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!tracking_code) return;
    let cancelled = false;

    const fetchOnce = async () => {
      const { data, error } = await supabase.rpc('track_order', { p_tracking_code: tracking_code });
      if (cancelled) return;
      setLoading(false);
      if (error || !data) { setNotFound(true); return; }
      setData(data as TrackingPayload);
    };

    void fetchOnce();
    timer.current = window.setInterval(fetchOnce, POLL_MS);
    return () => {
      cancelled = true;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [tracking_code]);

  if (loading) return <div className="p-6 text-center text-slate-500">Loading…</div>;
  if (notFound || !data) return <div className="p-6 text-center text-slate-500">Tracking code not found.</div>;

  const markers: MapMarker[] = data.driver_position
    ? [{
        id: 'driver',
        lat: data.driver_position.lat,
        lng: data.driver_position.lng,
        label: 'Driver',
        tone: 'primary',
      }]
    : [];

  const itemTotal = data.items.reduce((n, it) => n + Number(it.price) * it.quantity, 0);

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <header className="text-center">
        <h1 className="text-lg font-semibold">Order tracking</h1>
        <code className="text-xs text-slate-500">{data.tracking_code}</code>
      </header>

      <div className="rounded border border-slate-200 bg-white p-3">
        <StatusPill status={data.status} />
      </div>

      {data.driver_position && (
        <section>
          <h2 className="mb-2 text-sm font-medium text-slate-600">Driver location</h2>
          <MapWrapper
            markers={markers}
            center={{ lat: data.driver_position.lat, lng: data.driver_position.lng }}
            zoom={14}
            className="h-64 w-full rounded-lg"
          />
          <p className="mt-1 text-xs text-slate-500">
            Updated {new Date(data.driver_position.updated_at).toLocaleTimeString()}
          </p>
        </section>
      )}

      <section className="space-y-2 rounded border border-slate-200 bg-white p-3 text-sm">
        <Row icon={<MapPin className="h-4 w-4" />} label="Pickup branch">{data.pickup_branch}</Row>
        <Row icon={<Truck className="h-4 w-4" />} label="Delivery address">{data.delivery_address}</Row>
        <Row icon={<Clock className="h-4 w-4" />} label="Placed">
          {new Date(data.created_at).toLocaleString()}
        </Row>
        {data.dispatched_at && (
          <Row icon={<Clock className="h-4 w-4" />} label="Dispatched">
            {new Date(data.dispatched_at).toLocaleString()}
          </Row>
        )}
        {data.delivered_at && (
          <Row icon={<Clock className="h-4 w-4" />} label="Delivered">
            {new Date(data.delivered_at).toLocaleString()}
          </Row>
        )}
      </section>

      <section className="rounded border border-slate-200 bg-white">
        <h2 className="border-b border-slate-200 px-3 py-2 text-sm font-medium">
          <span className="inline-flex items-center gap-2"><Package className="h-4 w-4" /> Items</span>
        </h2>
        <ul className="divide-y">
          {data.items.map((it, i) => (
            <li key={i} className="flex justify-between px-3 py-2 text-sm">
              <span>{it.name} × {it.quantity}</span>
              <span>{(Number(it.price) * it.quantity).toFixed(2)}</span>
            </li>
          ))}
          {data.items.length === 0 && <li className="px-3 py-3 text-sm text-slate-400">No items.</li>}
        </ul>
        <div className="flex justify-between border-t border-slate-200 px-3 py-2 text-sm font-medium">
          <span>Total</span><span>{itemTotal.toFixed(2)}</span>
        </div>
      </section>
    </div>
  );
}

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 text-slate-400">{icon}</span>
      <div>
        <div className="text-xs text-slate-500">{label}</div>
        <div>{children}</div>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone: Record<string, string> = {
    pending: 'bg-slate-100 text-slate-700',
    confirmed: 'bg-blue-100 text-blue-700',
    picked: 'bg-indigo-100 text-indigo-700',
    dispatched: 'bg-amber-100 text-amber-800',
    in_transit: 'bg-amber-100 text-amber-800',
    delivered: 'bg-green-100 text-green-700',
    cancelled: 'bg-red-100 text-red-700',
    failed: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`inline-block rounded px-3 py-1 text-xs font-medium uppercase ${tone[status] ?? 'bg-slate-100'}`}>
      {status.replace('_', ' ')}
    </span>
  );
}
