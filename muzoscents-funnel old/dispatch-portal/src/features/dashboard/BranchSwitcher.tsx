import { useEffect, useState } from 'react';
import { supabase } from '../../lib/supabase';

interface Branch { id: string; name: string; }

export function BranchSwitcher({
  value, onChange,
}: { value: string | null; onChange: (id: string | null) => void }) {
  const [branches, setBranches] = useState<Branch[]>([]);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('branches').select('id,name').order('name');
      setBranches((data as Branch[]) ?? []);
    })();
  }, []);

  return (
    <select
      className="rounded border border-slate-300 px-3 py-1.5 text-sm"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">All branches (global)</option>
      {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>
  );
}
