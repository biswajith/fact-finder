import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Button, InlineAlert, Heading, Content, TextArea } from '@adobe/react-spectrum';
import * as api from '../api';
import { errorText, useRun } from '../store';
import type { ChatEvent, ChatMessage, ToolStep } from '../types';
import { planLines, planMessage } from '../chatBlocks';
import { ConflictCard } from './ConflictCard';
import { ErrorBox, Loading } from './common';
import { ChatMarkdown } from './chat/Markdown';

const STARTERS = [
  'What are the key dates?',
  'Which requirements are mandatory?',
  'Do any conflicts need my choice?',
  'List the facts I have changed.',
];

function ChatText({ text, role, streaming = false }: { text: string; role: 'user' | 'assistant'; streaming?: boolean }) {
  return role === 'user' ? <>{text}</> : <ChatMarkdown text={text} streaming={streaming} />;
}

function Tools({ tools }: { tools: ToolStep[] }) {
  return (
    <>
      {tools.map((t, i) => (
        <div key={i} className={`tool-line${t.ok ? '' : ' bad'}`} title={typeof t.args?.query === 'string' ? t.args.query : undefined}>
          <span aria-hidden>{t.ok ? '✓' : '✕'}</span>
          <span>{t.label}{t.ok ? '' : ' (failed)'}</span>
        </div>
      ))}
    </>
  );
}

function ConflictRefs({ ids }: { ids: string[] }) {
  const { conflicts } = useRun();
  return (
    <>
      {ids.map((id) => {
        const c = conflicts.data?.find((x) => x.id === id);
        return c ? <ConflictCard key={id} conflict={c} /> : <div key={id} className="muted">Conflict {id}{conflicts.loading ? '' : ' is not available.'}</div>;
      })}
    </>
  );
}

/** A plan the assistant shows before it works: numbered steps, a long topic list as tags, then its question. */
function PlanCard({ steps, rest, waiting }: { steps: NonNullable<ReturnType<typeof planMessage>>['steps']; rest: string; waiting: boolean }) {
  return (
    <div className="plan-card">
      <div className="plan-card-head">
        <strong>Plan</strong>
        <span className="muted">{steps.length} {steps.length === 1 ? 'step' : 'steps'}{waiting ? ' · waiting for your answer' : ''}</span>
      </div>
      <ol className="plan-steps">
        {steps.map((s, i) => (
          <li key={i} className={s.done ? 'done' : undefined}>
            <span className="plan-no" aria-hidden="true">{s.done ? '✓' : i + 1}</span>
            <div className="plan-step">
              <span>{s.text}</span>
              {s.items.length > 0 && (
                <ul className="plan-items" aria-label="Including">
                  {s.items.map((x) => <li key={x}>{x}</li>)}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ol>
      {rest && <div className="plan-card-foot"><ChatMarkdown text={rest} /></div>}
    </div>
  );
}

function Message({ m, waiting = false }: { m: ChatMessage; waiting?: boolean }) {
  const plan = m.role === 'assistant' && m.text ? planMessage(m.text) : null;
  return (
    <div className="msg-wrap">
      {m.role === 'assistant' && m.tools && <Tools tools={m.tools} />}
      {plan ? <PlanCard steps={plan.steps} rest={plan.rest} waiting={waiting} /> : m.text && (
        <div className={`msg ${m.role}`}>
          <ChatText text={m.text} role={m.role} />
        </div>
      )}
      {m.conflict_ids && m.conflict_ids.length > 0 && <ConflictRefs ids={m.conflict_ids} />}
    </div>
  );
}

interface Pending { text: string; tools: ToolStep[]; conflictIds: string[] }

/** Under a plan that waits for a yes: proceed, or say no and change the plan (or drop it). */
function PlanReply({ m, disabled, onSend }: { m: ChatMessage; disabled: boolean; onSend: (text: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => planLines(m.planning));
  if (!editing) {
    return (
      <div className="plan-reply" role="group" aria-label="Answer the plan">
        <Button variant="accent" isDisabled={disabled} onPress={() => onSend('Yes, go ahead.')}>Yes, proceed</Button>
        <Button variant="secondary" isDisabled={disabled} onPress={() => setEditing(true)}>No, change the plan</Button>
      </div>
    );
  }
  return (
    <div className="plan-reply editing" role="group" aria-label="Change the plan">
      <TextArea label="The plan, as you want it" value={draft} onChange={setDraft} width="100%" autoFocus />
      <div className="row">
        <Button variant="accent" isDisabled={disabled || !draft.trim()} onPress={() => onSend(`Change the plan to this, then show it to me again:\n${draft.trim()}`)}>Send the changed plan</Button>
        <Button variant="secondary" isDisabled={disabled} onPress={() => onSend('No, cancel that plan.')}>Drop the plan</Button>
        <Button variant="secondary" isQuiet onPress={() => setEditing(false)}>Back</Button>
      </div>
    </div>
  );
}

export function ChatPanel({ open, onClose, resizer }: { open: boolean; onClose: () => void; resizer?: ReactNode }) {
  const { run, status, reloadAll, chatDraft, setChatDraft, setSummaries, chatEpoch } = useRun();
  const [history, setHistory] = useState<ChatMessage[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const noKey = status !== null && !status.has_key;
  const sending = pending !== null;

  const loadHistory = useCallback(async () => {
    setLoadError(null);
    try {
      setHistory(await api.getChat(run));
    } catch (e) {
      setLoadError(errorText(e));
    }
  }, [run]);

  useEffect(() => {
    abortRef.current?.abort();
    setHistory(null);
    setPending(null);
    setStreamError(null);
    void loadHistory();
    return () => abortRef.current?.abort();
  }, [loadHistory, chatEpoch]);

  // "Ask in chat" puts a draft here.
  useEffect(() => {
    if (chatDraft) {
      setInput(chatDraft);
      setChatDraft('');
    }
  }, [chatDraft, setChatDraft]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, pending]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || sending || noKey) return;
    setInput('');
    setStreamError(null);
    const now = new Date().toISOString();
    setHistory((h) => [...(h ?? []), { id: `local_${now}`, role: 'user', at: now, text: message }]);
    const state: Pending = { text: '', tools: [], conflictIds: [] };
    setPending({ ...state });
    const ac = new AbortController();
    abortRef.current = ac;
    let final: ChatMessage | null = null;
    let failure = '';
    const onEvent = (e: ChatEvent) => {
      switch (e.type) {
        case 'text': state.text += e.delta; break;
        case 'tool': state.tools = [...state.tools, { name: e.name, label: e.label, ok: e.ok }]; break;
        case 'conflict': state.conflictIds = [...state.conflictIds, e.conflict_id]; void reloadAll(); break;
        case 'changed': void reloadAll(); break;
        case 'error': failure = e.message; setStreamError(e.message); break;
        case 'done':
          // A failed turn is stored with the error as its text; the error card already shows it.
          final = e.message;
          if (failure && e.message.text === failure) setStreamError(null);
          break;
      }
      setPending({ ...state, tools: state.tools, conflictIds: state.conflictIds });
    };
    try {
      await api.streamChat(run, message, onEvent, ac.signal);
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setStreamError(errorText(e));
    }
    if (ac.signal.aborted) return;
    setPending(null);
    if (final) {
      const done: ChatMessage = final;
      setHistory((h) => [...(h ?? []), done]);
    } else if (state.text || state.tools.length) {
      // The stream ended without a final message: keep what arrived.
      setHistory((h) => [...(h ?? []), { id: `local_a_${Date.now()}`, role: 'assistant', at: new Date().toISOString(), text: state.text, tools: state.tools, conflict_ids: state.conflictIds }]);
    }
    void reloadAll();
    // Summaries may have started rebuilding; make sure the poller notices.
    void api.getSummaries(run).then(setSummaries).catch(() => undefined);
  };

  const clear = async () => {
    try {
      await api.clearChat(run);
      setHistory([]);
      setStreamError(null);
    } catch (e) {
      setStreamError(errorText(e));
    }
  };

  const empty = history !== null && history.length === 0 && !pending;
  // The last message is a plan the assistant is waiting on: offer the answers as buttons.
  const lastMessage = history && history.length ? history[history.length - 1] : null;
  const waitingPlan = !pending && lastMessage?.role === 'assistant' && lastMessage.planning?.status === 'awaiting_approval' ? lastMessage : null;
  return (
    <aside className={`chat-panel${open ? ' open' : ''}`} id="app-chat" aria-label="Assistant">
      {resizer}
      <div className="chat-head">
        <strong>Assistant</strong>
        <div className="row">
          <Button variant="secondary" isQuiet isDisabled={sending || !history?.length} onPress={clear}>Clear chat</Button>
          <Button variant="secondary" isQuiet onPress={onClose} aria-label="Close assistant">Close</Button>
        </div>
      </div>
      <div className="chat-log" ref={logRef} aria-live="polite" aria-label="Chat messages" role="log">
        {loadError ? (
          <ErrorBox message={loadError} onRetry={() => void loadHistory()} />
        ) : history === null ? (
          <Loading label="Loading chat" />
        ) : (
          history.map((m) => <Message key={m.id} m={m} waiting={m === waitingPlan} />)
        )}
        {waitingPlan && <PlanReply key={waitingPlan.id} m={waitingPlan} disabled={sending || noKey} onSend={(t) => void send(t)} />}
        {pending && (
          <div className="msg-wrap">
            <Tools tools={pending.tools} />
            {pending.text ? <div className="msg assistant"><ChatText text={pending.text} role="assistant" streaming /></div> : <div className="muted">Working...</div>}
            {pending.conflictIds.length > 0 && <ConflictRefs ids={pending.conflictIds} />}
          </div>
        )}
        {streamError && (
          <InlineAlert variant="negative">
            <Heading>The assistant could not answer</Heading>
            <Content><span className="wrap-text">{streamError}</span></Content>
          </InlineAlert>
        )}
        {empty && (
          <div className="card">
            <div>Ask about this RFP or tell me what to correct. For example:</div>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} type="button" className="chip" disabled={noKey} onClick={() => void send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="chat-input">
        {noKey && (
          <InlineAlert variant="notice">
            <Heading>Chat is switched off</Heading>
            <Content>No API key is set on the server, so the assistant cannot answer. You can still read and edit facts.</Content>
          </InlineAlert>
        )}
        <TextArea
          label="Message"
          value={input}
          onChange={setInput}
          isDisabled={noKey}
          width="100%"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send(input);
            }
          }}
        />
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="muted">Enter sends, Shift+Enter adds a line.</span>
          <Button variant="accent" isDisabled={noKey || sending || !input.trim()} onPress={() => void send(input)}>
            {sending ? 'Sending...' : 'Send'}
          </Button>
        </div>
      </div>
    </aside>
  );
}
