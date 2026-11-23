import type { ReactNode } from 'react';
import { levelChip, useBidDocs } from '../../bidDocs';
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

export function Tag({ tone = 'neutral', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return <span className={`fx-tag ${tone}`} title={title}>{children}</span>;
}

const FLAG_TONE: Record<Flag, Tone> = {
  mandatory: 'danger', desirable: 'accent', risk: 'warn', unclear: 'neutral', replaced: 'neutral', 'post-award': 'ok',
  tentative: 'warn', precedence: 'accent', 'both-sides': 'neutral',
};
const FLAG_TEXT: Partial<Record<Flag, string>> = { 'both-sides': 'both sides' };
const FLAG_TIP: Partial<Record<Flag, string>> = { 'both-sides': 'Question and answer: both sides' };
export const flagName = (x: string): string => FLAG_TEXT[x as Flag] ?? x;

/** Flags, status and provenance of a fact as small tags. In a bid: its level, and "Replaced" in place of the flag. */
export function FactTags({ f, stated = 1 }: { f: Fact; stated?: number }) {
  const { inBid } = useBidDocs();
  const flags = inBid ? f.flags.filter((x) => x !== 'replaced') : f.flags;
  return (
    <>
      {inBid && f.level ? <Tag tone="accent">{levelChip(f.level)}</Tag> : null}
      {inBid && f.flags.includes('replaced') && <Tag>Replaced</Tag>}
      {flags.map((x) => <Tag key={x} tone={FLAG_TONE[x] ?? 'neutral'} title={FLAG_TIP[x]}>{flagName(x)}</Tag>)}
      {f.status !== 'valid' && <Tag tone={f.status === 'conflict' ? 'danger' : 'warn'}>{STATUS_LABEL[f.status] ?? f.status}</Tag>}
      {f.also && <Tag>also {categoryName(f.also)}</Tag>}
      {f.split && <Tag tone="warn">split vote{f.agreement ? ` ${f.agreement}` : ''}</Tag>}
      {stated > 1 && <Tag>stated {stated} times</Tag>}
      {f.deleted ? <Tag>Deleted</Tag> : f.origin === 'user' ? <Tag tone="accent">Added</Tag> : f.edited ? <Tag tone="accent">Changed</Tag> : null}
    </>
  );
}
