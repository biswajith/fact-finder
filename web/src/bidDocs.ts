import { useMemo } from 'react';
import { bidDocs, type BidDocs } from './bidView';
import { useRun } from './store';

export * from './bidView';

/** The documents of the open run when it is a bid; `inBid` is false for a single-document run. */
export function useBidDocs(): BidDocs {
  const { facts } = useRun();
  const documents = facts.data?.documents;
  return useMemo(() => bidDocs(documents), [documents]);
}
