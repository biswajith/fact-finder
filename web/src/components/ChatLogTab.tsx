import { useCallback, useEffect, useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { argsText, cacheShare, fmtNum, fmtSecs, fmtUsd, groupTurns, purposeLabel, turnTotals, type Turn } from '../chatLog';
import { errorText, useRun } from '../store';
import type { ChatLogEvent, ChatSession, ChatSessionDetail, ChatTotals } from '../types';
import { ErrorBox, Loading, formatTime } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';
import './chatlog.css';

const VERDICT_TONE: Record<string, string> = { approve: 'ok', revise: 'warn', cancel: 'danger', new_request: '' };
const STATUS_LABEL: Record<string, string> = {
  awaiting_approval: 'Waiting for approval',
  approved: 'Approved',
  cancelled: 'Cancelled',
};

const pct = (p?: number | null) => (p == null ? '' : `${Math.round(p * 100)}%`);

function Totals({ totals, turns }: { totals: ChatTotals; turns?: number }) {
  const costHint = totals.cost_usd != null
    ? `LLM ${fmtUsd(totals.llm_cost_usd ?? 0)} · Decisions ${fmtUsd(totals.decisions_cost_usd ?? 0)}`
    : 'not priced: no price for the model used';
  const tiles: { l: string; v: string; h?: string }[] = [
    { l: 'Estimated cost', v: fmtUsd(totals.cost_usd), h: costHint },
    ...(turns !== undefined ? [{ l: 'Turns', v: fmtNum(turns) }] : []),
    { l: 'LLM calls', v: fmtNum(totals.llm_calls ?? 0), h: totals.llm_seconds ? `${fmtSecs(totals.llm_seconds)} waiting` : undefined },
    { l: 'Tool calls', v: fmtNum(totals.tool_calls ?? 0) },
    { l: 'Decisions calls', v: fmtNum(totals.decisions_calls ?? 0),
      h: totals.decisions_input_tokens ? `${fmtNum(totals.decisions_input_tokens)} input tokens` : undefined },
    { l: 'Input tokens', v: fmtNum(totals.input_tokens ?? 0), h: `${cacheShare(totals.input_tokens, totals.cached_tokens)} cached` },
    { l: 'Output tokens', v: fmtNum(totals.output_tokens ?? 0) },
  ];
  return (
    <div className="cl-stats">
      {tiles.map((t) => (
        <div key={t.l} className="cl-stat">
          <span className="l">{t.l}</span>
          <span className="v">{t.v}</span>
          {t.h && <span className="h">{t.h}</span>}
        </div>
      ))}
    </div>
  );
}

function SessionList({ sessions, selected, onSelect }: { sessions: ChatSession[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="cl-sessions" role="listbox" aria-label="Chat sessions">
      {sessions.map((s) => (
        <button
          key={s.session_id}
          type="button"
          role="option"
          aria-selected={s.session_id === selected}
          className="cl-session"
          onClick={() => onSelect(s.session_id)}
        >
          <span className="top">
            <span className="when">{formatTime(s.started)}</span>
            {s.current && <span className="pg-pill info">Current</span>}
          </span>
          <span className="id">{s.session_id}</span>
          <span className="meta">
            {s.turns} turn{s.turns === 1 ? '' : 's'} · {fmtNum(s.totals.llm_calls ?? 0)} LLM calls
            {s.totals.cost_usd != null ? ` · ${fmtUsd(s.totals.cost_usd)}` : ''}
          </span>
        </button>
      ))}
    </div>
  );
}

function Decision({ label, e, value, tone }: { label: string; e: ChatLogEvent; value: string; tone?: string }) {
  const bits = [e.source, pct(e.confidence) && `confidence ${pct(e.confidence)}`, e.call?.seconds != null && fmtSecs(e.call.seconds),
    e.call?.input_tokens != null && `${fmtNum(e.call.input_tokens)} tokens`,
    e.call?.cost_usd != null && fmtUsd(e.call.cost_usd)].filter(Boolean);
  return (
    <div className="cl-decision">
      <span className="k">{label}</span>
      <span className={`pg-pill ${tone ?? 'info'}`}>{value}</span>
      <span className="muted">{bits.join(' · ')}</span>
      {e.note && <span className="cl-note">{e.note}</span>}
      {e.call?.error && <span className="cl-err">{e.call.error}</span>}
    </div>
  );
}

function Plan({ e, updates }: { e: ChatLogEvent; updates: number }) {
  const status = e.status ? STATUS_LABEL[e.status] ?? e.status : '';
  return (
    <div className="cl-plan">
      <div className="cl-plan-head">
        <span className="k">Plan</span>
        {status && <span className={`pg-pill ${e.status === 'approved' ? 'ok' : e.status === 'cancelled' ? 'danger' : 'warn'}`}>{status}</span>}
        {updates > 1 && <span className="muted">updated {updates - 1}×</span>}
      </div>
      {e.steps && e.steps.length > 0 ? (
        <ol className="cl-steps">
          {e.steps.map((s, i) => (
            <li key={i} className={s.done ? 'done' : ''}>
              <span className="mark" aria-label={s.done ? 'done' : 'not done'}>{s.done ? '✓' : '○'}</span>
              <span>{s.step}</span>
            </li>
          ))}
        </ol>
      ) : (
        e.plan_text && <p className="cl-plan-text">{e.plan_text}</p>
      )}
    </div>
  );
}

function Calls({ turn }: { turn: Turn }) {
  if (!turn.calls.length) return null;
  return (
    <div className="cl-table-wrap">
      <table className="cl-table">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Call</th>
            <th scope="col">Asked for</th>
            <th scope="col" className="num">Input</th>
            <th scope="col" className="num">Cached</th>
            <th scope="col" className="num">Output</th>
            <th scope="col" className="num">Cost</th>
            <th scope="col" className="num">Time</th>
          </tr>
        </thead>
        <tbody>
          {turn.calls.map(({ call, tools }, i) => (
            <CallRows key={call.seq} n={i + 1} call={call} tools={tools} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CallRows({ n, call, tools }: { n: number; call: ChatLogEvent; tools: ChatLogEvent[] }) {
  const asked = call.tool_calls ?? [];
  const what = asked.length
    ? `${asked.length} tool call${asked.length === 1 ? '' : 's'}`
    : call.text_chars
      ? `text (${fmtNum(call.text_chars)} chars)`
      : 'nothing';
  return (
    <>
      <tr className={`cl-call${call.error ? ' failed' : ''}`}>
        <td>{n}</td>
        <td>
          <span className="cl-purpose">{purposeLabel(call.purpose)}</span>
          {call.round != null && <span className="muted"> · round {call.round}</span>}
          {!call.tools_allowed && call.tools_offered ? <span className="muted"> · tools off</span> : null}
          {call.error && <div className="cl-err">{call.error}</div>}
        </td>
        <td>{what}</td>
        <td className="num">{fmtNum(call.input_tokens)}</td>
        <td className="num">{call.input_tokens ? `${fmtNum(call.cached_tokens)} (${cacheShare(call.input_tokens, call.cached_tokens)})` : '–'}</td>
        <td className="num">{fmtNum(call.output_tokens)}</td>
        <td className="num">{fmtUsd(call.cost_usd)}</td>
        <td className="num">{fmtSecs(call.seconds)}</td>
      </tr>
      {tools.map((t) => (
        <tr key={t.seq} className={`cl-tool${t.ok ? '' : ' failed'}`}>
          <td />
          <td colSpan={2}>
            <span className={`cl-tool-name${t.ok ? '' : ' bad'}`}>{t.ok ? '✓' : '✗'} {t.name}</span>
            {argsText(t.args) && <span className="cl-args"> {argsText(t.args)}</span>}
            {t.summary && <div className="muted cl-summary">{t.summary}</div>}
          </td>
          <td colSpan={4} />
          <td className="num">{fmtSecs(t.seconds)}</td>
        </tr>
      ))}
    </>
  );
}

function TurnCard({ turn, n }: { turn: Turn; n: number }) {
  const totals = turnTotals(turn);
  const error = turn.end?.error;
  return (
    <li className={`cl-turn${error ? ' failed' : ''}`} aria-label={`Turn ${n}`}>
      <div className="cl-turn-head">
        <span className="cl-turn-n">Turn {n}</span>
        <span className="muted">{formatTime(turn.at)}</span>
        <span className="tl-spacer" />
        {totals.cost_usd != null && <span className="cl-cost">{fmtUsd(totals.cost_usd)}</span>}
        <span className="muted">
          {fmtNum(totals.llm_calls ?? 0)} LLM · {fmtNum(totals.tool_calls ?? 0)} tools
          {totals.decisions_calls ? ` · ${totals.decisions_calls} decisions` : ''} · {fmtNum(totals.input_tokens ?? 0)} in
          ({cacheShare(totals.input_tokens, totals.cached_tokens)} cached) · {fmtNum(totals.output_tokens ?? 0)} out
          {totals.seconds != null ? ` · ${fmtSecs(totals.seconds)}` : ''}
        </span>
      </div>
      {turn.user !== undefined && (
        <div className="cl-msg user">
          <span className="k">Customer</span>
          <p>{turn.user}</p>
        </div>
      )}
      {(turn.feedback || turn.route) && (
        <div className="cl-decisions">
          {turn.feedback && <Decision label="Feedback on the plan" e={turn.feedback} value={turn.feedback.verdict ?? '?'} tone={VERDICT_TONE[turn.feedback.verdict ?? ''] ?? ''} />}
          {turn.route && <Decision label="Planning mode" e={turn.route} value={turn.route.mode ?? '?'} />}
        </div>
      )}
      {turn.plan && (turn.plan.steps?.length || turn.plan.plan_text) ? <Plan e={turn.plan} updates={turn.planUpdates} /> : null}
      <Calls turn={turn} />
      {turn.reply && (
        <details className="cl-reply">
          <summary>Reply <span className="muted">({fmtNum(turn.reply.text?.length ?? 0)} chars)</span></summary>
          <p>{turn.reply.text}</p>
        </details>
      )}
      {error && <div className="cl-err">{error}</div>}
      {!turn.end && <div className="muted">This turn has no end record: it is still running, or the server stopped during it.</div>}
    </li>
  );
}

export function ChatLogTab() {
  const { run } = useRun();
  const [sessions, setSessions] = useState<ChatSession[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadSessions = useCallback(async () => {
    setError(null);
    try {
      const list = await api.getChatSessions(run);
      setSessions(list);
      setSelected((cur) => (cur && list.some((s) => s.session_id === cur) ? cur : (list[0]?.session_id ?? null)));
    } catch (e) {
      setError(errorText(e));
    }
  }, [run]);

  const loadDetail = useCallback(async (id: string) => {
    setLoadingDetail(true);
    try {
      setDetail(await api.getChatSession(run, id));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoadingDetail(false);
    }
  }, [run]);

  useEffect(() => {
    setSessions(null);
    setDetail(null);
    setSelected(null);
    void loadSessions();
  }, [loadSessions]);
  useEffect(() => {
    if (selected) void loadDetail(selected);
    else setDetail(null);
  }, [selected, loadDetail]);

  const refresh = () => {
    void loadSessions();
    if (selected) void loadDetail(selected);
  };

  if (error && !sessions) return <ErrorBox message={error} onRetry={refresh} />;
  if (!sessions) return <Loading label="Loading chat sessions" />;
  const turns = detail ? groupTurns(detail.events) : [];
  const session = detail?.session ?? sessions.find((s) => s.session_id === selected) ?? null;
  return (
    <>
      <PageHeader
        title="Chat log"
        subtitle={sessions.length ? `${sessions.length} session${sessions.length === 1 ? '' : 's'} · what each message cost and what the assistant did` : undefined}
        actions={<Button variant="secondary" onPress={refresh}>Refresh</Button>}
      />
      <div className="pg-stack">
        {error && <ErrorBox message={error} onRetry={refresh} />}
        {sessions.length === 0 ? (
          <div className="pg-empty">
            <strong>No chat sessions yet</strong>
            <span>Send a message to the Assistant; each message and every model call it makes is logged here.
              Clearing the chat starts a new session.</span>
          </div>
        ) : (
          <>
            <SessionList sessions={sessions} selected={selected} onSelect={setSelected} />
            {session && (
              <section className="cl-detail" aria-label={`Session ${session.session_id}`}>
                <h2 className="pg-h2">
                  Session <code>{session.session_id}</code>
                  {session.started && <span className="muted cl-started"> · started {formatTime(session.started)}</span>}
                </h2>
                <Totals totals={session.totals} turns={session.turns} />
                <p className="pg-note">
                  Costs are estimates from the model price list at the time each turn was logged (GPT-6 Luna: $0.10 per
                  1M input tokens, $0.01 cached, $0.50 output; Decisions API: input only). Summary rebuilds that a change
                  starts are not included.
                </p>
                {loadingDetail && !detail ? (
                  <Loading label="Loading the session log" />
                ) : turns.length === 0 ? (
                  <p className="pg-note">This session has no logged turns.</p>
                ) : (
                  <ol className="cl-turns">
                    {turns.map((t, i) => <TurnCard key={t.id} turn={t} n={i + 1} />)}
                  </ol>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
