import { useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import { rowsInOrder } from '../../bid';
import type { Bid } from '../../types';

export function PrecedenceOrder({ bid, onSet }: { bid: Bid; onSet: (order: string[] | null) => Promise<boolean> }) {
  const level1 = rowsInOrder(bid).filter((d) => bid.playbooks.find((p) => p.name === d.playbook)?.level === '1');
  const ids = level1.map((d) => d.doc_id);
  // Highest first: what the buyer set, else the later issue first, which is what wins without an order.
  const start = [...(bid.precedence ?? []).filter((id) => ids.includes(id)), ...[...ids].reverse().filter((id) => !(bid.precedence ?? []).includes(id))];
  const [order, setOrder] = useState(start);
  const [busy, setBusy] = useState(false);
  const label = (id: string) => {
    const d = level1.find((x) => x.doc_id === id);
    return d ? `d${d.no} ${d.file_name}` : id;
  };
  const move = (i: number, by: number) =>
    setOrder((o) => {
      const next = [...o];
      [next[i], next[i + by]] = [next[i + by], next[i]];
      return next;
    });
  const run = async (fn: () => Promise<boolean>) => {
    setBusy(true);
    await fn();
    setBusy(false);
  };

  return (
    <details className="pg-fold" open={!!bid.precedence}>
      <summary>Order of precedence (optional){bid.precedence ? ': set' : ''}</summary>
      <p className="muted">Set this only when the buyer states which document governs. Otherwise the later issue wins.</p>
      {order.length < 2 ? (
        <div className="muted">Needs at least two buyer documents.</div>
      ) : (
        <>
          <ol className="pg-precedence" aria-label="Documents, highest precedence first">
            {order.map((id, i) => (
              <li key={id}>
                <span className="grow wrap-text">{label(id)}</span>
                <Button variant="secondary" aria-label={`Move ${label(id)} up`} isDisabled={i === 0 || busy} onPress={() => move(i, -1)}>Up</Button>
                <Button variant="secondary" aria-label={`Move ${label(id)} down`} isDisabled={i === order.length - 1 || busy} onPress={() => move(i, 1)}>Down</Button>
              </li>
            ))}
          </ol>
          <div className="pg-actions">
            <Button variant="accent" isDisabled={busy} onPress={() => void run(() => onSet(order))}>Confirm order</Button>
            <Button variant="secondary" isDisabled={busy || !bid.precedence} onPress={() => void run(() => onSet(null))}>Clear (later issue wins)</Button>
          </div>
        </>
      )}
    </details>
  );
}
