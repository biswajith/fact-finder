import { useState } from 'react';
import { Button, Flex } from '@adobe/react-spectrum';
import { rowsInOrder } from '../../bid';
import type { Bid } from '../../types';
import '../intake/intake.css';

/** Which buyer document wins when they disagree: the order the buyer states, else the later issue wins. */
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
    <div>
      <p className="in-muted" style={{ marginTop: 0 }}>Set this only when the buyer states which document governs. Otherwise the later issue wins.</p>
      {order.length < 2 ? (
        <div className="in-muted">Needs at least two buyer documents.</div>
      ) : (
        <>
          <ol className="in-precedence" aria-label="Documents, highest precedence first">
            {order.map((id, i) => (
              <li key={id}>
                <span className="in-grow in-text">{label(id)}</span>
                <Button variant="secondary" aria-label={`Move ${label(id)} up`} isDisabled={i === 0 || busy} onPress={() => move(i, -1)}>Up</Button>
                <Button variant="secondary" aria-label={`Move ${label(id)} down`} isDisabled={i === order.length - 1 || busy} onPress={() => move(i, 1)}>Down</Button>
              </li>
            ))}
          </ol>
          <Flex gap="size-150" wrap>
            <Button variant="accent" isDisabled={busy} onPress={() => void run(() => onSet(order))}>Confirm order</Button>
            <Button variant="secondary" isDisabled={busy || !bid.precedence} onPress={() => void run(() => onSet(null))}>Clear (later issue wins)</Button>
          </Flex>
        </>
      )}
    </div>
  );
}
