import { useRun } from '../store';
import { firstPage } from './common';

export const SHORT_CATEGORY: Record<string, string> = {
  B: 'Buyer', C: 'Contract', G: 'Gate', X: 'DQ', D: 'Date', S: 'Submit', E: 'Eval', R: 'Req', Q: 'Conflict',
};

/** One fact as a pill: "Req · p.4", tooltip = the fact text. Used in chat. */
export function CiteChip({ id }: { id: string }) {
  const { openFact, factById } = useRun();
  const f = factById.get(id);
  const page = f ? firstPage(f) : '';
  const label = f ? [SHORT_CATEGORY[f.category] ?? f.category, page ? `p.${page}` : ''].filter(Boolean).join(' · ') : 'fact';
  return (
    <button type="button" className="cite" aria-label={`Open fact ${id}`} title={f ? f.text : id} onClick={() => openFact(id)}>
      {label}
    </button>
  );
}

const MAX_PAGES = 4;
const clip = (s: string) => (s.length > 120 ? `${s.slice(0, 119)}…` : s);

interface Group { page: string; ids: string[] }

const pageOrder = (a: string, b: string) => {
  if (a === '') return b === '' ? 0 : 1;
  if (b === '') return -1;
  const x = parseFloat(a), y = parseFloat(b);
  if (!Number.isNaN(x) && !Number.isNaN(y) && x !== y) return x - y;
  return a.localeCompare(b, undefined, { numeric: true });
};

/** Citations for a point: one pill per distinct page ("p.7 ·3"), at most four, then "+N". */
export function PageCites({ ids }: { ids: string[] }) {
  const { openFact, factById } = useRun();
  const by = new Map<string, string[]>();
  for (const id of ids) {
    const f = factById.get(id);
    const p = f ? firstPage(f) : '';
    by.set(p, [...(by.get(p) ?? []), id]);
  }
  const groups: Group[] = [...by].map(([page, g]) => ({ page, ids: g })).sort((a, b) => pageOrder(a.page, b.page));
  if (groups.length === 0) return null;
  const tip = (g: string[]) => g.map((id) => clip(factById.get(id)?.text ?? id)).join('\n');
  const shown = groups.slice(0, MAX_PAGES);
  const rest = groups.slice(MAX_PAGES);
  const restIds = rest.flatMap((g) => g.ids);
  return (
    <span className="cite-group">
      {shown.map((g) => (
        <button key={g.page || '?'} type="button" className="cite" aria-label={`Open fact ${g.ids[0]}`} title={tip(g.ids)} onClick={() => openFact(g.ids[0])}>
          {g.page ? `p.${g.page}` : 'fact'}{g.ids.length > 1 ? ` ·${g.ids.length}` : ''}
        </button>
      ))}
      {rest.length > 0 && (
        <button type="button" className="cite" aria-label={`Open fact ${restIds[0]}`} title={tip(restIds)} onClick={() => openFact(restIds[0])}>
          +{rest.length}
        </button>
      )}
    </span>
  );
}
