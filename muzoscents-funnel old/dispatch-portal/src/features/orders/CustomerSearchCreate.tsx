import { useEffect, useRef, useState } from 'react';
import { Search, UserPlus, Check } from 'lucide-react';
import { supabase, type Customer } from '../../lib/supabase';
import { useDebouncedValue } from '../../lib/hooks/useDebouncedValue';

interface Props {
  value: Customer | null;
  onChange: (c: Customer | null) => void;
}

export function CustomerSearchCreate({ value, onChange }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const debounced = useDebouncedValue(query, 350);
  const reqId = useRef(0);

  useEffect(() => {
    if (value || debounced.trim().length < 2) { setResults([]); return; }
    const id = ++reqId.current;
    setLoading(true);

    (async () => {
      const raw = debounced.trim();
      // Cheap normalization matching the DB trigger's intent, so "0803 123-4567"
      // and "08031234567" hit the same row.
      const digits = raw.replace(/\D/g, '').replace(/^00/, '');
      const orFilter = digits.length >= 7
        ? `phone.ilike.%${digits}%,name.ilike.%${raw}%`
        : `name.ilike.%${raw}%`;

      const { data, error } = await supabase
        .from('customers')
        .select('id,name,phone,email,address')
        .or(orFilter)
        .limit(8);

      if (id !== reqId.current) return; // stale response
      setLoading(false);
      if (error) { setResults([]); return; }
      setResults((data as Customer[]) ?? []);
    })();
  }, [debounced, value]);

  if (value) {
    return (
      <div className="flex items-center justify-between rounded border border-green-300 bg-green-50 px-3 py-2">
        <div className="flex items-center gap-2 text-sm">
          <Check className="h-4 w-4 text-green-600" />
          <span className="font-medium">{value.name}</span>
          <span className="text-slate-500">{value.phone}</span>
        </div>
        <button
          type="button"
          className="text-xs text-slate-600 underline"
          onClick={() => { onChange(null); setQuery(''); setShowCreate(false); }}
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          className="w-full rounded border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
          placeholder="Search customers by phone or name…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setShowCreate(false); }}
        />
        {loading && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">…</span>}
      </div>

      {results.length > 0 && (
        <ul className="max-h-56 divide-y overflow-auto rounded border border-slate-200 bg-white shadow-sm">
          {results.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
                onClick={() => { onChange(c); setResults([]); }}
              >
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-slate-500">{c.phone}{c.address ? ` · ${c.address}` : ''}</div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!loading && debounced.trim().length >= 2 && results.length === 0 && !showCreate && (
        <button
          type="button"
          className="flex items-center gap-2 text-sm text-blue-600 hover:underline"
          onClick={() => setShowCreate(true)}
        >
          <UserPlus className="h-4 w-4" />
          No match — create a new customer
        </button>
      )}

      {showCreate && (
        <NewCustomerForm
          initialName={/^\d/.test(debounced) ? '' : debounced}
          initialPhone={/^\d/.test(debounced) ? debounced : ''}
          onCreated={(c) => { onChange(c); setShowCreate(false); setQuery(''); }}
          onCancel={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}

function NewCustomerForm({
  initialName, initialPhone, onCreated, onCancel,
}: {
  initialName: string;
  initialPhone: string;
  onCreated: (c: Customer) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [phone, setPhone] = useState(initialPhone);
  const [address, setAddress] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);

    const digits = phone.replace(/\D/g, '').replace(/^00/, '');
    if (!name.trim()) return setErr('Name is required');
    if (digits.length < 7 || digits.length > 15) return setErr('Enter a valid phone number');

    setSaving(true);
    const { data, error } = await supabase
      .from('customers')
      .insert({
        name: name.trim(),
        phone: digits,             // DB trigger will re-normalize anyway
        email: email.trim() ? email.trim().toLowerCase() : null,
        address: address.trim() || null,
      })
      .select('id,name,phone,email,address')
      .single();
    setSaving(false);

    if (error) {
      // Unique violation on phone -> the customer already exists; fetch them.
      if (error.code === '23505') {
        const { data: existing } = await supabase
          .from('customers')
          .select('id,name,phone,email,address')
          .eq('phone', digits)
          .maybeSingle();
        if (existing) return onCreated(existing as Customer);
      }
      return setErr(error.message);
    }
    onCreated(data as Customer);
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded border border-blue-200 bg-blue-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">New customer</div>
      <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Full name"
             value={name} onChange={(e) => setName(e.target.value)} />
      <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Phone"
             value={phone} onChange={(e) => setPhone(e.target.value)} />
      <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Email (optional)"
             value={email} onChange={(e) => setEmail(e.target.value)} />
      <input className="w-full rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Address"
             value={address} onChange={(e) => setAddress(e.target.value)} />
      {err && <div className="text-xs text-red-600">{err}</div>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {saving ? 'Saving…' : 'Create & link'}
        </button>
        <button type="button" onClick={onCancel}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm">
          Cancel
        </button>
      </div>
    </form>
  );
}
