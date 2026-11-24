import type { BidFlow } from '../../bidFlow';
import type { Status } from '../../types';
import { BidsList } from '../intake/BidsList';
import { Wizard } from '../intake/Wizard';

/** Documents: the list of bids, or, once one is opened (or a new one is started), its intake wizard. */
export function DocumentsPage({ flow, status }: { flow: BidFlow; status: Status | null }) {
  return flow.showing ? <Wizard flow={flow} status={status} /> : <BidsList flow={flow} />;
}
