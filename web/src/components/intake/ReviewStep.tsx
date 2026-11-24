import {
  AlertDialog, Badge, Button, Content, ContextualHelp, DialogTrigger, Disclosure, DisclosurePanel, DisclosureTitle, Flex, Heading, InlineAlert, Item, LabeledValue,
  Picker,
} from '@adobe/react-spectrum';
import { levelLabel, missingWords, playbookLabel, rowsInOrder, showPrecedence } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import { callsOf, playbookOf, speakersUnread } from '../../intake';
import { extractCount } from '../../bid';
import type { Status } from '../../types';
import { ErrorBox } from '../common';
import { PrecedenceOrder } from '../bid/PrecedenceOrder';
import { FileBadge } from './parts';
import './intake.css';

const ACCURACY: Record<number, string> = { 1: 'Draft: one reading', 3: 'Standard: three readings vote', 5: 'High: five readings vote' };

/** Step 4: the reading order, the plan of model calls for the accuracy chosen, and the button that starts it. */
export function ReviewStep({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const { bid, plan } = flow;
  if (!bid) return null;
  const read = rowsInOrder(bid).filter((d) => d.confirmed);
  const left = bid.documents.filter((d) => !d.confirmed);
  const noSpeakers = callsOf(bid).filter((d) => !d.run && (d.speakers.length === 0 || speakersUnread(d)));
  const planned = (plan?.documents ?? []).filter((d) => d.missing.length === 0 && !d.error);
  const waiting = (plan?.documents ?? []).filter((d) => d.missing.length > 0);
  const n = extractCount(plan);
  const rebuild = n === 0 && !!bid.run;
  const units = planned.reduce((t, d) => t + d.units, 0);
  const calls = planned.filter((d) => !d.stored).reduce((t, d) => t + d.total_calls, 0);
  const hasKey = !!status?.has_key;
  const canStart = hasKey && !!plan && waiting.length === 0 && (n > 0 || rebuild) && !flow.running;
  const fileOf = (no: number) => bid.documents.find((d) => d.no === no)?.file_name ?? '';

  return (
    <div className="in-grid2">
      <div>
        <section className="in-card" aria-labelledby="order-h">
          <h2 id="order-h">Reading order</h2>
          <p className="in-lede">Documents are read in the order they were issued, so a later addendum can replace what the RFP said.</p>
          <ol className="in-timeline">
            {read.map((d) => {
              const pb = playbookOf(bid, d);
              return (
                <li key={d.no}>
                  <span className="in-when">{d.issue_date ?? 'No date'}</span>
                  <span className={`in-pip${pb?.role === 'change' ? ' chg' : pb?.role === 'context' ? ' ctx' : ''}`} aria-hidden />
                  <div style={{ minWidth: 0 }}>
                    <Flex alignItems="center" gap="size-100">
                      <FileBadge name={d.file_name} />
                      <div style={{ minWidth: 0 }}>
                        <div className="in-ellipsis" title={d.file_name}>{d.file_name}</div>
                        <div className="in-muted in-small">{playbookLabel(d.playbook)}{d.issue_number ? ` ${d.issue_number}` : ''}{pb ? ` · ${levelLabel(pb)}` : ''}</div>
                      </div>
                    </Flex>
                  </div>
                  {pb?.visibility === 'internal' ? <Badge variant="purple">Internal</Badge> : <Badge variant="neutral">Buyer</Badge>}
                </li>
              );
            })}
          </ol>
          <Flex gap="size-100" marginTop="size-100">
            <Button variant="secondary" style="outline" onPress={() => flow.setStep('documents')}>Change documents</Button>
          </Flex>
        </section>

        {showPrecedence(bid) && (
          <section className="in-card" aria-label="Which document wins">
            <Disclosure isQuiet defaultExpanded={!!bid.precedence}>
              <DisclosureTitle>Which document wins{bid.precedence ? ': set' : ''}</DisclosureTitle>
              <DisclosurePanel>
                <PrecedenceOrder
                  key={bid.bid_id + bid.documents.map((d) => `${d.doc_id}:${d.playbook}`).join() + JSON.stringify(bid.precedence)}
                  bid={bid}
                  onSet={flow.setPrecedence}
                />
              </DisclosurePanel>
            </Disclosure>
          </section>
        )}
      </div>

      <div>
        <section className="in-card" aria-labelledby="cost-h">
          <Flex alignItems="center" gap="size-50">
            <h2 id="cost-h">Before you start</h2>
            <ContextualHelp variant="info">
              <Heading>How the plan works</Heading>
              <Content>Each unit of text is labelled several times and the readings vote. More readings mean more model calls and agree more often. Nothing is spent until you start.</Content>
            </ContextualHelp>
          </Flex>
          <p className="in-lede">The plan is counted from your documents; no model is called to make it.</p>
          <Flex direction="column" gap="size-200">
            <Picker label="Accuracy" selectedKey={String(flow.votes)} onSelectionChange={(k) => flow.setVotes(Number(k))} width="100%">
              <Item key="1">{ACCURACY[1]}</Item>
              <Item key="3">{ACCURACY[3]}</Item>
              <Item key="5">{ACCURACY[5]}</Item>
            </Picker>
            {flow.planError ? (
              <ErrorBox message={`Could not plan the calls: ${flow.planError}`} onRetry={flow.replan} />
            ) : !plan ? (
              <div className="in-muted" role="status">{flow.planLoading ? 'Counting the documents...' : 'Confirm a document to see the plan.'}</div>
            ) : (
              <>
                <div className="in-stats">
                  <div className="in-stat"><div className="in-v">{units.toLocaleString()}</div><div className="in-l">units of text</div></div>
                  <div className="in-stat"><div className="in-v">{calls.toLocaleString()}</div><div className="in-l">model calls</div></div>
                </div>
                {planned.length > 0 && (
                  <table className="in-plan" aria-label="Planned calls by document">
                    <thead><tr><th scope="col">Document</th><th scope="col" className="in-num">Units</th><th scope="col" className="in-num">Calls</th></tr></thead>
                    <tbody>
                      {planned.map((d) => (
                        <tr key={d.no}>
                          <td>d{d.no} {d.file_name}{d.stored ? <div className="in-muted in-small">A stored result is reused ({d.stored.facts} facts), so no calls.</div> : null}</td>
                          <td className="in-num">{d.units}</td>
                          <td className="in-num">{d.stored ? 0 : d.total_calls}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <div className="in-muted in-small">Grouping repeated points and checking facts that disagree add a few calls across the whole bid.</div>
                {plan.relate_again.length > 0 && (
                  <div className="in-muted in-small">Links from {plan.relate_again.map((no) => `d${no}`).join(', ')} will be read again because an earlier document was added.</div>
                )}
                {plan.documents.filter((d) => d.error).map((d) => <div key={d.no} className="in-bad in-small">d{d.no}: {d.error}</div>)}
              </>
            )}
          </Flex>
        </section>

        {(left.length > 0 || noSpeakers.length > 0 || waiting.length > 0) && (
          <InlineAlert variant="notice" marginTop="size-200">
            <Heading>Check before you start</Heading>
            <Content>
              <ul className="in-list">
                {left.length > 0 && <li>{left.length} unconfirmed {left.length === 1 ? 'document is' : 'documents are'} left out: {left.map((d) => d.file_name).join(', ')}.</li>}
                {noSpeakers.map((d) => <li key={d.no}>{d.file_name} has no speakers, so all of it counts as unclear.</li>)}
                {waiting.map((d) => <li key={d.no}>d{d.no} {fileOf(d.no)}: {missingWords(d.missing)}</li>)}
              </ul>
            </Content>
          </InlineAlert>
        )}
        {status && !hasKey && (
          <InlineAlert variant="negative" marginTop="size-200">
            <Heading>No API key</Heading>
            <Content>The API key is not set (in the environment or .env), so no extraction can start.</Content>
          </InlineAlert>
        )}
        {flow.startError && <div style={{ marginTop: 16 }}><ErrorBox message={flow.startError} /></div>}

        <section className="in-card" style={{ marginTop: 16 }}>
          <Flex alignItems="center" gap="size-200" wrap>
            <LabeledValue label="Documents" value={n} />
            <LabeledValue label="Accuracy" value={ACCURACY[flow.votes].split(':')[0]} />
            <div style={{ flex: 1 }} />
            {bid.run && <Button variant="secondary" style="outline" onPress={() => flow.openFacts(bid.run)}>Open the fact list</Button>}
            <DialogTrigger>
              <Button variant="accent" isDisabled={!canStart}>{rebuild ? 'Rebuild the fact list' : 'Start extraction'}</Button>
              <AlertDialog title={rebuild ? 'Rebuild the fact list?' : 'Start extraction?'} variant="confirmation" primaryActionLabel="Start" cancelLabel="Not yet" onPrimaryAction={() => void flow.start()}>
                {rebuild
                  ? 'The fact list will be built again from the results already stored. Checks across documents call the model.'
                  : `${n} ${n === 1 ? 'document' : 'documents'} will be read with ${calls.toLocaleString()} model calls. This spends API tokens. You can leave this page while it runs.`}
              </AlertDialog>
            </DialogTrigger>
          </Flex>
        </section>
      </div>
    </div>
  );
}
