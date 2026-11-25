import {
  AlertDialog, Badge, Button, ContextualHelp, Content, DialogTrigger, Flex, Heading, InlineAlert, Item, LabeledValue, Meter, Picker, Switch,
} from '@adobe/react-spectrum';
import { estimate, issueOrder, typeInfo } from '../data';
import { useIntake } from '../store';
import { FileBadge } from './DocumentsStep';

const ACCURACY: Record<number, string> = { 1: 'Draft: one reading', 3: 'Standard: three readings vote', 5: 'High: five readings vote' };

export function ReviewStep() {
  const { s, go, setVotes, setNotify, start } = useIntake();
  const docs = issueOrder(s.docs.filter((d) => d.confirmed));
  const left = s.docs.filter((d) => !d.confirmed);
  const e = estimate(docs, s.votes);
  const budget = 25;
  const unclearCalls = docs.filter((d) => typeInfo(d.type).spoken && !d.speakers.length);

  return (
    <>
      <div className="grid2">
        <section className="card" aria-labelledby="order-h">
          <h2 id="order-h">Reading order</h2>
          <p className="lede">Documents are read in the order they were issued, so a later addendum can replace what the RFP said.</p>
          <ol className="timeline">
            {docs.map((d) => {
              const t = typeInfo(d.type);
              return (
                <li key={d.id}>
                  <span className="when">{d.date ?? 'No date'}</span>
                  <span className={`pip${t.role === 'change' ? ' chg' : t.role === 'context' ? ' ctx' : ''}`} aria-hidden />
                  <div style={{ minWidth: 0 }}>
                    <Flex alignItems="center" gap="size-100">
                      <FileBadge format={d.format} />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</div>
                        <div className="muted small">{t.label}{d.number ? ` ${d.number}` : ''} · {t.level}</div>
                      </div>
                    </Flex>
                  </div>
                  {t.internal ? <Badge variant="purple">Internal</Badge> : <Badge variant="neutral">Buyer</Badge>}
                </li>
              );
            })}
          </ol>
          <Flex gap="size-100" marginTop="size-100">
            <Button variant="secondary" style="outline" onPress={() => go('documents')}>Change documents</Button>
          </Flex>
        </section>

        <div>
          <section className="card" aria-labelledby="cost-h">
            <Flex alignItems="center" gap="size-50">
              <h2 id="cost-h">Before you start</h2>
              <ContextualHelp variant="info">
                <Heading>How the estimate works</Heading>
                <Content>Each unit of text is labelled several times and the readings vote. More readings cost more and agree more often. The estimate uses this bid's page counts; the real cost is shown after the run.</Content>
              </ContextualHelp>
            </Flex>
            <p className="lede">Nothing is spent until you start.</p>
            <Flex direction="column" gap="size-200">
              <Picker label="Accuracy" selectedKey={String(s.votes)} onSelectionChange={(k) => setVotes(Number(k))} width="100%">
                <Item key="1">{ACCURACY[1]}</Item>
                <Item key="3">{ACCURACY[3]}</Item>
                <Item key="5">{ACCURACY[5]}</Item>
              </Picker>
              <div className="stats" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
                <div className="stat"><div className="v">{e.units.toLocaleString()}</div><div className="l">units of text</div></div>
                <div className="stat"><div className="v">{e.calls.toLocaleString()}</div><div className="l">model calls</div></div>
                <div className="stat"><div className="v">${e.dollars.toFixed(2)}</div><div className="l">estimated cost</div></div>
                <div className="stat"><div className="v">~{e.minutes} min</div><div className="l">estimated time</div></div>
              </div>
              <Meter label="This month's budget" value={Math.min(100, ((11.4 + e.dollars) / budget) * 100)} valueLabel={`$${(11.4 + e.dollars).toFixed(2)} of $${budget}`}
                variant={(11.4 + e.dollars) / budget > 0.9 ? 'critical' : (11.4 + e.dollars) / budget > 0.7 ? 'warning' : 'positive'} width="100%" />
              <Switch isSelected={s.notify} onChange={setNotify}>Email me when it is done</Switch>
            </Flex>
          </section>

          {(left.length > 0 || unclearCalls.length > 0) && (
            <InlineAlert variant="notice" marginTop="size-200">
              <Heading>Check before you start</Heading>
              <Content>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {left.length > 0 && <li>{left.length} unconfirmed {left.length === 1 ? 'document is' : 'documents are'} left out: {left.map((d) => d.name).join(', ')}.</li>}
                  {unclearCalls.map((d) => <li key={d.id}>{d.name} has no speakers, so all of it counts as unclear.</li>)}
                </ul>
              </Content>
            </InlineAlert>
          )}

          <section className="card" style={{ marginTop: 16 }}>
            <Flex alignItems="center" gap="size-200">
              <LabeledValue label="Documents" value={docs.length} />
              <LabeledValue label="Accuracy" value={ACCURACY[s.votes].split(':')[0]} />
              <div style={{ flex: 1 }} />
              <DialogTrigger>
                <Button variant="accent">Start extraction</Button>
                <AlertDialog title="Start extraction?" variant="confirmation" primaryActionLabel="Start" cancelLabel="Not yet" onPrimaryAction={start}>
                  {docs.length} documents will be read with {e.calls.toLocaleString()} model calls, about ${e.dollars.toFixed(2)} and {e.minutes} minutes.
                  You can leave this page while it runs.
                </AlertDialog>
              </DialogTrigger>
            </Flex>
          </section>
        </div>
      </div>
    </>
  );
}
