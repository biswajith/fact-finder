import type { ReactNode } from 'react';
import type { CategoryCode, Fact, FactStatus, Flag } from '../../types';
import { CATEGORY_NAMES } from '../../types';

export const STATUS_LABEL: Record<FactStatus, string> = { valid: 'valid', needs_review: 'needs review', conflict: 'conflict' };

export const categoryName = (c: string): string => CATEGORY_NAMES[c as CategoryCode] ?? c;

/** Category as its full short name, text in the category colour on its soft tint. */
export function CatPill({ code }: { code: string }) {
  return (
    <span className="fx-cat" style={{ color: `var(--cat-${code}, var(--cat-B))`, background: `var(--cat-${code}-soft, var(--cat-B-soft))` }}>
      {categoryName(code)}
    </span>
  );
}

export type Tone = 'neutral' | 'danger' | 'warn' | 'ok' | 'accent';

export function Tag({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`fx-tag ${tone}`}>{children}</span>;
}

const FLAG_TONE: Record<Flag, Tone> = {
  mandatory: 'danger', desirable: 'accent', risk: 'warn', unclear: 'neutral', replaced: 'neutral', 'post-award': 'ok',
};

/** Flags, status and provenance of a fact as small tags. */
export function FactTags({ f, stated = 1 }: { f: Fact; stated?: number }) {
  return (
    <>
      {f.flags.map((x) => <Tag key={x} tone={FLAG_TONE[x] ?? 'neutral'}>{x}</Tag>)}
      {f.status !== 'valid' && <Tag tone={f.status === 'conflict' ? 'danger' : 'warn'}>{STATUS_LABEL[f.status] ?? f.status}</Tag>}
      {f.also && <Tag>also {categoryName(f.also)}</Tag>}
      {f.split && <Tag tone="warn">split vote{f.agreement ? ` ${f.agreement}` : ''}</Tag>}
      {stated > 1 && <Tag>stated {stated} times</Tag>}
      {f.deleted ? <Tag>Deleted</Tag> : f.origin === 'user' ? <Tag tone="accent">Added</Tag> : f.edited ? <Tag tone="accent">Changed</Tag> : null}
    </>
  );
}
