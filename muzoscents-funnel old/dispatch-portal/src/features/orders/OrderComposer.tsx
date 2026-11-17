import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { supabase, type Customer, type Product } from '../../lib/supabase';
import { useProfile } from '../../lib/hooks/useProfile';
import { CustomerSearchCreate } from './CustomerSearchCreate';
import { ProductSearch } from './ProductSearch';
import { DriverAssignment } from './DriverAssignment';

interface LineItem { product: Product; quantity: number; }

export function OrderComposer({ onCreated }: { onCreated?: (orderId: string) => void }) {
  const { profile } = useProfile();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [items, setItems] = useState<LineItem[]>([]);
  const [driverId, setDriverId] = useState<string | null>(null);
  const [deliveryAddress, setDeliveryAddress] = useState('');
  const [dispatchCost, setDispatchCost] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const subtotal = useMemo(
    () => items.reduce((n, li) => n + li.product.price * li.quantity, 0),
    [items],
  );

  const branchId = profile?.branch_id ?? null;

  if (!profile || !branchId) {
    return <div className="p-4 text-sm text-slate-500">Loading branch context…</div>;
  }

  function addProduct(p: Product) {
    setItems((prev) => {
      const existing = prev.find((li) => li.product.id === p.id);
      if (existing) return prev.map((li) => li.product.id === p.id ? { ...li, quantity: li.quantity + 1 } : li);
      return [...prev, { product: p, quantity: 1 }];
    });
  }

  async function submit() {
    setErr(null);
    if (!profile) return null;
    if (!customer) return setErr('Select or create a customer first.');
    if (items.length === 0) return setErr('Add at least one product.');
    if (!deliveryAddress.trim()) return setErr('Delivery address is required.');

    setSaving(true);

    // Single atomic RPC. Prices are read from products server-side; the
    // client only sends product_id + quantity.
    const payload = {
      p_customer_id: customer.id,
      p_delivery_address: deliveryAddress.trim(),
      p_dispatch_cost: dispatchCost ? Number(dispatchCost) : null,
      p_assigned_driver_id: driverId,
      p_items: items.map((li) => ({
        product_id: li.product.id,
        quantity: li.quantity,
      })),
      p_branch_id: profile.role === 'master' ? branchId : null,
    };

    console.log('RPC payload being sent:', payload);

    const { data, error } = await supabase.rpc('create_order_with_items', payload);

    setSaving(false);

    if (error) {
      // Log everything PostgREST gives us so we can see exactly what failed.
      console.error('RPC error', {
        message: error.message,
        details: error.details,
        hint: error.hint,
        code: error.code,
      });
      return setErr(
        `${error.message}${error.hint ? ' — ' + error.hint : ''}${error.code ? ' [' + error.code + ']' : ''}`,
      );
    }

    const row = Array.isArray(data) ? data[0] : data;
    if (!row?.id) return setErr('Order creation returned no id');

    onCreated?.(row.id);
    setCustomer(null); setItems([]); setDriverId(null);
    setDeliveryAddress(''); setDispatchCost('');
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4">
      <h2 className="text-lg font-semibold">New order</h2>

      <section className="space-y-2">
        <label className="text-xs font-medium text-slate-600">Customer</label>
        <CustomerSearchCreate value={customer} onChange={(c) => {
          setCustomer(c);
          if (c?.address && !deliveryAddress) setDeliveryAddress(c.address);
        }} />
      </section>

      <section className="space-y-2">
        <label className="text-xs font-medium text-slate-600">Products</label>
        <ProductSearch branchId={branchId} onAdd={addProduct} excludeIds={items.map((li) => li.product.id)} />
        {items.length > 0 && (
          <ul className="divide-y rounded border border-slate-200">
            {items.map((li) => (
              <li key={li.product.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <div>
                  <div className="font-medium">{li.product.name}</div>
                  <div className="text-xs text-slate-500">{li.product.sku ?? '—'} · {li.product.price.toFixed(2)}</div>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number" min={1}
                    className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                    value={li.quantity}
                    onChange={(e) => {
                      const q = Math.max(1, Number(e.target.value) || 1);
                      setItems((prev) => prev.map((x) => x.product.id === li.product.id ? { ...x, quantity: q } : x));
                    }}
                  />
                  <span className="w-20 text-right text-xs text-slate-600">
                    {(li.product.price * li.quantity).toFixed(2)}
                  </span>
                  <button onClick={() => setItems((prev) => prev.filter((x) => x.product.id !== li.product.id))}>
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="text-right text-sm font-medium">Subtotal: {subtotal.toFixed(2)}</div>
      </section>

      <section className="space-y-2">
        <label className="text-xs font-medium text-slate-600">Delivery address</label>
        <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
               value={deliveryAddress} onChange={(e) => setDeliveryAddress(e.target.value)} />
      </section>

      <section className="space-y-2">
        <label className="text-xs font-medium text-slate-600">Dispatch cost (optional)</label>
        <input type="number" step="0.01" min={0}
               className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
               value={dispatchCost} onChange={(e) => setDispatchCost(e.target.value)} />
      </section>

      <DriverAssignment branchId={branchId} value={driverId} onChange={setDriverId} />

      {err && <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <button
        onClick={submit}
        disabled={saving}
        className="w-full rounded bg-blue-600 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {saving ? 'Creating…' : 'Create order'}
      </button>
    </div>
  );
}
