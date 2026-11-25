import { Button, Content, Disclosure, DisclosurePanel, DisclosureTitle, Flex, Heading, IllustratedMessage, ProgressBar, ProgressCircle, StatusLight, ToastQueue } from '@adobe/react-spectrum';
import CheckmarkCircle from '@spectrum-icons/workflow/CheckmarkCircle';
import { issueOrder, typeInfo } from '../data';
import { useIntake, type Task } from '../store';
import { FileBadge } from './DocumentsStep';

const clock = (ms: number) => {
  const t = Math.round(ms / 1000);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
};

function TaskLine({ t }: { t: Task }) {
  return (
    <div className={`task ${t.status}`}>
      {t.status === 'done' ? <CheckmarkCircle size="S" color="positive" aria-label="done" />
        : t.status === 'running' ? <ProgressCircle size="S" isIndeterminate aria-label="running" />
        : <span aria-label="waiting" style={{ width: 18, height: 18, borderRadius: '50%', border: '2px solid var(--spectrum-global-color-gray-400)', boxSizing: 'border-box' }} />}
      <span>{t.label}</span>
      <span className="muted small">{t.status === 'running' ? `${Math.round((1 - t.left / t.total) * 100)}%` : ''}</span>
    </div>
  );
}

export function RunStep() {
  const { s, view } = useIntake();
  const run = s.run;
  if (!run) return null;
  const total = run.tasks.reduce((n, t) => n + t.total, 0);
  const done = run.tasks.reduce((n, t) => n + (t.total - t.left), 0);
  const pct = Math.round((done / total) * 100);
  const remaining = Math.max(0, total - done);
  const docs = issueOrder(s.docs.filter((d) => d.confirmed));
  const bidTasks = run.tasks.filter((t) => !t.docId);
  const facts = Object.values(run.facts).reduce((n, f) => n + f, 0);

  if (run.done) {
    return (
      <>
        <section className="card">
          <IllustratedMessage>
            <CheckmarkCircle size="XXL" color="positive" />
            <Heading>The fact list is ready</Heading>
            <Content>{docs.length} documents read in {clock(run.elapsed)}. Check the conflicts first: they are where the documents disagree.</Content>
          </IllustratedMessage>
          <div className="stats" style={{ marginTop: 24 }}>
            <div className="stat"><div className="v">{facts}</div><div className="l">facts</div></div>
            <div className="stat"><div className="v">{Math.max(1, Math.round(facts * 0.03))}</div><div className="l">conflicts to settle</div></div>
            <div className="stat"><div className="v">{Math.max(1, Math.round(facts * 0.07))}</div><div className="l">facts replaced by a later document</div></div>
            <div className="stat"><div className="v">{Math.max(1, Math.round(facts * 0.05))}</div><div className="l">need a person to check</div></div>
          </div>
          <Flex gap="size-150" justifyContent="center" marginTop="size-300">
            <Button variant="secondary" style="outline" onPress={() => view('bids')}>Back to bids</Button>
            <Button variant="secondary" onPress={() => ToastQueue.neutral('The conflicts page is not part of this mock', { timeout: 3000 })}>Review conflicts</Button>
            <Button variant="accent" onPress={() => ToastQueue.neutral('The fact list is not part of this mock', { timeout: 3000 })}>Open the fact list</Button>
          </Flex>
        </section>
        <section className="card">
          <h2>By document</h2>
          {docs.map((d) => (
            <Flex key={d.id} alignItems="center" gap="size-150" UNSAFE_style={{ padding: '8px 0', borderBottom: '1px solid var(--spectrum-global-color-gray-200)' }}>
              <FileBadge format={d.format} />
              <div style={{ flex: 1, minWidth: 0 }}><strong>{d.name}</strong><div className="muted small">{typeInfo(d.type).label}</div></div>
              <span>{run.facts[d.id] ?? 0} facts</span>
            </Flex>
          ))}
        </section>
      </>
    );
  }

  const running = run.tasks.find((t) => t.status === 'running');
  return (
    <>
      <section className="card" aria-live="polite">
        <Flex alignItems="end" gap="size-200">
          <div style={{ flex: 1 }}>
            <h2>Reading the bid</h2>
            <p className="lede" style={{ margin: 0 }}>{running ? `${running.label}${running.docId ? ` · ${s.docs.find((d) => d.id === running.docId)?.name}` : ''}` : 'Starting'}</p>
          </div>
          <div className="muted small" style={{ textAlign: 'right' }}>Elapsed {clock(run.elapsed)}<br />About {clock(remaining)} left</div>
        </Flex>
        <ProgressBar label="Overall" value={pct} width="100%" marginTop="size-200" />
        <p className="muted small" style={{ marginBottom: 0 }}>
          You can leave this page. {s.notify ? 'We will email you when it is done.' : 'The bid shows its progress in the list.'}
        </p>
      </section>
      <section className="card">
        {docs.map((d) => {
          const tasks = run.tasks.filter((t) => t.docId === d.id);
          const state = tasks.every((t) => t.status === 'done') ? 'done' : tasks.some((t) => t.status !== 'waiting') ? 'running' : 'waiting';
          return (
            <div className="docrun" key={d.id}>
              <Disclosure isExpanded={state === 'running' ? true : undefined} defaultExpanded={false} isQuiet>
                <DisclosureTitle>
                  <Flex alignItems="center" gap="size-150" width="100%">
                    <FileBadge format={d.format} />
                    <span style={{ fontWeight: 600 }}>{d.name}</span>
                    <div style={{ flex: 1 }} />
                    {state === 'done' ? <StatusLight variant="positive">{`${run.facts[d.id] ?? 0} facts`}</StatusLight>
                      : state === 'running' ? <StatusLight variant="info">Reading</StatusLight> : <StatusLight variant="neutral">Waiting</StatusLight>}
                  </Flex>
                </DisclosureTitle>
                <DisclosurePanel>
                  <div className="tasks">{tasks.map((t) => <TaskLine key={t.id} t={t} />)}</div>
                </DisclosurePanel>
              </Disclosure>
            </div>
          );
        })}
        <div className="docrun">
          <strong>The whole bid</strong>
          <div className="tasks">{bidTasks.map((t) => <TaskLine key={t.id} t={t} />)}</div>
        </div>
      </section>
    </>
  );
}
