import { useEffect, useRef, useState } from 'react';
import { Search, Plus } from 'lucide-react';
import { supabase, type Product } from '../../lib/supabase';
import { useDebouncedValue } from '../../lib/hooks/useDebouncedValue';

interface Props {
  branchId: string;
  onAdd: (p: Product) => void;
  excludeIds?: string[];
}

export function ProductSearch({ branchId, onAdd, excludeIds = [] }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const debounced = useDebouncedValue(query, 300);
  const reqId = useRef(0);

  useEffect(() => {
    if (debounced.trim().length < 1) { setResults([]); return; }
    const id = ++reqId.current;

    (async () => {
      const raw = debounced.trim();
      // RLS already restricts to the officer's branch; the explicit filter
      // keeps the intent readable and safe if the officer is later given a
      // cross-branch scope.
      const { data, error } = await supabase
        .from('products')
        .select('id,branch_id,sku,name,price')
        .eq('branch_id', branchId)
        .eq('is_active', true)
        .or(`sku.ilike.%${raw}%,name.ilike.%${raw}%`)
        .limit(8);

      if (id !== reqId.current) return;
      setResults(error ? [] : (data as Product[]) ?? []);
    })();
  }, [debounced, branchId]);

  const visible = results.filter((r) => !excludeIds.includes(r.id));

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input
        className="w-full rounded border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
        placeholder="Add product by SKU or name…"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && visible.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-64 w-full divide-y overflow-auto rounded border border-slate-200 bg-white shadow-lg">
          {visible.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { onAdd(p); setQuery(''); setResults([]); setOpen(false); }}
              >
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-slate-500">{p.sku ?? '—'}</div>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-700">
                  {p.price.toFixed(2)}
                  <Plus className="h-3.5 w-3.5" />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
