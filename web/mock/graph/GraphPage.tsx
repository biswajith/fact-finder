import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import { Icon } from './Icon';
import {
  allFacts, ask, fieldAt, nodeReview, nodeStep, nodesOfFact, REVIEW_TEXT, sourceLabel, STATUS_TEXT,
  type GNode, type Graph, type Hit, type Review,
} from './model';

cytoscape.use(fcose);

type Theme = 'light' | 'dark';
type LayoutName = 'zones' | 'force' | 'rings';

/** The zones of the map: each node type sits in one. The deal stays outside, in the middle. */
const ZONES: { id: string; label: string; types: string[]; color: string }[] = [
  { id: 'z_buyer', label: 'Buyer, people and why they buy', types: ['organization', 'person', 'driver', 'competitor'], color: '#0284c7' },
  { id: 'z_scope', label: 'What they buy and what it replaces', types: ['solution', 'process', 'system', 'phase', 'requirement'], color: '#059669' },
  { id: 'z_win', label: 'Submission, gates and scoring', types: ['submission_item', 'gate', 'reference', 'method', 'criterion'], color: '#7c3aed' },
  { id: 'z_contract', label: 'Contract and insurance', types: ['contract_term', 'insurance'], color: '#475569' },
  { id: 'z_time', label: 'Key dates', types: ['event'], color: '#d97706' },
  { id: 'z_open', label: 'Risks, actions and open questions', types: ['risk', 'action', 'question'], color: '#e11d48' },
];
const ZONE_OF: Record<string, string> = Object.fromEntries(ZONES.flatMap((z) => z.types.map((t) => [t, z.id])));

const EDGE_COLORS: Record<string, string> = {
  then: '#d97706', '180 days after': '#d97706', 'anchored to': '#d97706',
  satisfies: '#16a34a', 'would satisfy': '#16a34a', fails: '#dc2626', threatens: '#e11d48',
  closes: '#9333ea', owner: '#9333ea', about: '#0891b2', answered: '#0891b2', replaces: '#78716c',
  'must pass': '#dc2626', 'must avoid': '#dc2626', 'competes for': '#b45309',
};

function mix(hex: string, other: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [a, b] = [p(hex), p(other)];
  return `rgb(${a.map((v, i) => Math.round(v * (1 - t) + b[i] * t)).join(',')})`;
}

function cyStyle(theme: Theme): cytoscape.CytoscapeOptions['style'] {
  const dark = theme === 'dark';
  const text = dark ? '#e7e9ec' : '#1b1f26';
  const bg = dark ? '#14161a' : '#ffffff';
  return [
    { selector: 'node', style: {
      'background-color': 'data(tint)', 'border-color': 'data(color)', 'border-width': 2.5, shape: 'data(shape)' as never,
      width: 'data(size)', height: 'data(size)', label: 'data(label)', color: text, 'font-size': 11, 'font-weight': 500,
      'text-valign': 'bottom', 'text-margin-y': 6, 'text-wrap': 'wrap', 'text-max-width': '130px',
      'text-background-color': bg, 'text-background-opacity': 0.82, 'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle', 'min-zoomed-font-size': 7,
      'transition-property': 'opacity, border-width, underlay-opacity', 'transition-duration': 220,
    } },
    { selector: 'node[type="deal"]', style: {
      'background-color': 'data(color)', 'border-color': dark ? '#c7d2fe' : '#ffffff', 'border-width': 4,
      'font-size': 15, 'font-weight': 700, 'text-max-width': '200px',
    } },
    { selector: 'node.needs_review', style: {
      'underlay-color': '#ef4444', 'underlay-padding': 9, 'underlay-opacity': 0.28, 'underlay-shape': 'ellipse',
    } },
    { selector: 'node.settled', style: {
      'underlay-color': '#f59e0b', 'underlay-padding': 6, 'underlay-opacity': 0.24, 'underlay-shape': 'ellipse',
    } },
    { selector: 'node.not_final', style: { 'border-style': 'dashed' } },
    { selector: 'node[status="removed"]', style: { opacity: 0.38, 'border-style': 'dotted' } },
    { selector: 'node.hover', style: { 'border-width': 4.5, 'z-index': 20 } },
    { selector: 'node:selected', style: {
      'underlay-color': '#3b82f6', 'underlay-opacity': 0.36, 'underlay-padding': 13, 'underlay-shape': 'ellipse',
      'border-width': 4.5, 'z-index': 30,
    } },
    { selector: 'node.fresh', style: {
      'underlay-color': '#22c55e', 'underlay-opacity': 0.45, 'underlay-padding': 16, 'underlay-shape': 'ellipse',
    } },
    { selector: 'edge', style: {
      width: 1.3, 'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'triangle',
      'arrow-scale': 0.75, 'curve-style': 'bezier', opacity: 0.5, label: 'data(edge)', 'font-size': 9,
      color: dark ? '#a4abb6' : '#5a6372', 'text-opacity': 0, 'text-rotation': 'autorotate',
      'text-background-color': bg, 'text-background-opacity': 0.9, 'text-background-padding': '1px',
      'transition-property': 'opacity, width', 'transition-duration': 220,
    } },
    { selector: 'edge[edge="then"]', style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 4] } },
    { selector: 'edge.cross', style: { opacity: 0.13, 'curve-style': 'unbundled-bezier', 'control-point-distances': [40], 'control-point-weights': [0.5] } },
    { selector: 'edge.hl', style: { opacity: 1, width: 2.4, 'text-opacity': 1, 'z-index': 25 } },
    { selector: '.faded', style: { opacity: 0.09, 'text-opacity': 0 } },
    { selector: 'edge.faded', style: { opacity: 0.04 } },
    { selector: '.hidden', style: { display: 'none' } },
    { selector: 'node.zone', style: {
      shape: 'round-rectangle', 'background-color': 'data(color)', 'background-opacity': dark ? 0.07 : 0.045,
      'border-width': 1.5, 'border-style': 'dashed', 'border-color': 'data(color)', 'border-opacity': 0.4,
      label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -10, 'text-wrap': 'none',
      'font-weight': 700, color: 'data(color)', 'text-background-opacity': 0, padding: '30px', 'font-size': 20,
      'corner-radius': 28, 'min-zoomed-font-size': 4, 'underlay-opacity': 0, events: 'no',
    } as never },
    { selector: 'node.zone.dim', style: { 'background-opacity': 0.015, 'border-opacity': 0.15, 'text-opacity': 0.35 } },
  ] as never;
}

/** Elements for cytoscape, with sizes from link counts and colours from the node type. */
function elements(g: Graph, theme: Theme, zones: boolean): cytoscape.ElementDefinition[] {
  const degree: Record<string, number> = {};
  for (const l of g.links) {
    degree[l.from] = (degree[l.from] ?? 0) + 1;
    degree[l.to] = (degree[l.to] ?? 0) + 1;
  }
  const base = theme === 'dark' ? '#1c1f24' : '#ffffff';
  const edgeDefault = theme === 'dark' ? '#4b5563' : '#b8bfca';
  const nodes = g.nodes.map((n) => {
    const t = g.types[n.type];
    const d = degree[n.id] ?? 0;
    const size = n.type === 'deal' ? 78 : Math.round(Math.min(56, 20 + 6.5 * Math.sqrt(d)));
    const review = nodeReview(n);
    return {
      group: 'nodes' as const,
      data: {
        id: n.id, label: n.label, type: n.type, status: n.status, color: t.color, shape: t.shape, size,
        tint: mix(t.color, base, theme === 'dark' ? 0.55 : 0.8),
        ...(zones && ZONE_OF[n.type] ? { parent: ZONE_OF[n.type] } : {}),
      },
      classes: review ?? '',
    };
  });
  const parents = zones
    ? ZONES.map((z) => ({ group: 'nodes' as const, data: { id: z.id, label: z.label, color: z.color }, classes: 'zone' }))
    : [];
  const typeOf = new Map(g.nodes.map((n) => [n.id, n.type]));
  const edges = g.links.map((l, i) => ({
    group: 'edges' as const,
    data: { id: `e${i}`, source: l.from, target: l.to, edge: l.edge, color: EDGE_COLORS[l.edge] ?? edgeDefault },
    // links between zones stay quiet until a node or view lights them up
    classes: zones && ZONE_OF[typeOf.get(l.from) ?? ''] !== ZONE_OF[typeOf.get(l.to) ?? ''] ? 'cross' : '',
  }));
  return [...parents, ...nodes, ...edges];
}

function layoutOptions(name: LayoutName, animate: boolean): cytoscape.LayoutOptions {
  if (name === 'zones') {
    return {
      name: 'fcose', quality: 'proof', randomize: true, animate, animationDuration: 900, fit: true, padding: 30,
      nodeRepulsion: () => 9000, idealEdgeLength: (e: cytoscape.EdgeSingular) => (e.source().parent().same(e.target().parent()) ? 60 : 200),
      edgeElasticity: (e: cytoscape.EdgeSingular) => (e.source().parent().same(e.target().parent()) ? 0.45 : 0.08),
      nestingFactor: 0.12, gravity: 0.3, gravityCompound: 1.4, gravityRangeCompound: 1.2, nodeSeparation: 80,
      numIter: 4000, packComponents: false, tile: true, tilingPaddingVertical: 14, tilingPaddingHorizontal: 14,
    } as cytoscape.LayoutOptions;
  }
  if (name === 'rings') {
    return {
      name: 'concentric', animate, animationDuration: 700, minNodeSpacing: 26, startAngle: 0,
      concentric: (n: cytoscape.NodeSingular) => (n.data('type') === 'deal' ? 100 : 100 - (n.data('depth') ?? 6) * 10),
      levelWidth: () => 1,
    } as cytoscape.LayoutOptions;
  }
  return {
    name: 'fcose', quality: 'proof', randomize: true, animate, animationDuration: 900, fit: true, padding: 40,
    nodeRepulsion: () => 12000, idealEdgeLength: () => 80, edgeElasticity: () => 0.35, gravity: 0.22,
    gravityRange: 3.4, nodeSeparation: 90, numIter: 3500, packComponents: true, tile: true,
  } as cytoscape.LayoutOptions;
}

// ---------------------------------------------------------------- small pieces

function TypeShape({ color, size = 10 }: { color: string; size?: number }) {
  return <span className="tdot" style={{ background: color, width: size, height: size }} />;
}

function StatusPill({ status }: { status: keyof typeof STATUS_TEXT }) {
  if (status === 'none') return null;
  return <span className={`pill st-${status}`}>{STATUS_TEXT[status]}</span>;
}

function ReviewPill({ review }: { review: Review }) {
  if (!review) return null;
  return <span className={`pill rv-${review}`}>{REVIEW_TEXT[review]}</span>;
}

// ---------------------------------------------------------------- the page

export function GraphPage({ src }: { src: string }) {
  const [g, setG] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(() => (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  const [layout, setLayout] = useState<LayoutName>('zones');
  const [selected, setSelected] = useState<string | null>(null);
  const [lensKey, setLensKey] = useState<string | null>(null);
  const [rowIdx, setRowIdx] = useState<number | null>(null);
  const [reviewFilter, setReviewFilter] = useState<Exclude<Review, null> | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [query, setQuery] = useState('');
  const [askOpen, setAskOpen] = useState(false);
  const [askIdx, setAskIdx] = useState(0);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const [pop, setPop] = useState<{ id: string; x: number; y: number } | null>(null);
  const [factFocus, setFactFocus] = useState<string | null>(null);
  const [built, setBuilt] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const askRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(src).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${r.statusText}`))))
      .then((data: Graph) => { setG(data); setStep(data.documents.length - 1); })
      .catch((e: Error) => setError(`Could not load the graph: ${e.message}`));
  }, [src]);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  const byId = useMemo(() => new Map((g?.nodes ?? []).map((n) => [n.id, n])), [g]);
  const steps = useMemo(() => new Map((g?.nodes ?? []).map((n) => [n.id, g ? nodeStep(g, n) : 0])), [g]);
  const lens = g?.lenses.find((l) => l.key === lensKey) ?? null;
  const lastStep = (g?.documents.length ?? 1) - 1;

  // ---- build the canvas once per graph and theme
  useEffect(() => {
    if (!g || !boxRef.current) return;
    const cy = cytoscape({
      container: boxRef.current, elements: elements(g, theme, layout === 'zones'), style: cyStyle(theme),
      minZoom: 0.15, maxZoom: 3, wheelSensitivity: 0.25, boxSelectionEnabled: false,
    });
    // depth from the deal, for the rings layout
    cy.nodes(':childless').forEach((n) => { n.data('depth', 6); });
    cy.elements().bfs({
      roots: cy.$id('deal'), directed: false,
      visit: (v, _e, _u, _i, depth) => { v.data('depth', depth); },
    });
    cy.layout(layoutOptions(layout, false)).run();
    cy.on('tap', 'node:childless', (e) => { setSelected(e.target.id()); setFactFocus(null); });
    cy.on('tap', (e) => { if (e.target === cy) { setSelected(null); setFactFocus(null); } });
    cy.on('mouseover', 'node:childless', (e) => {
      const n = e.target as cytoscape.NodeSingular;
      n.addClass('hover');
      n.connectedEdges().addClass('hl');
      const p = n.renderedPosition();
      setHover({ id: n.id(), x: p.x, y: p.y - n.renderedHeight() / 2 });
      boxRef.current!.style.cursor = 'pointer';
    });
    cy.on('mouseout', 'node:childless', (e) => {
      const n = e.target as cytoscape.NodeSingular;
      n.removeClass('hover');
      if (!n.selected()) n.connectedEdges().removeClass('hl');
      setHover(null);
      boxRef.current!.style.cursor = '';
    });
    cy.on('pan zoom', () => setHover(null));
    cyRef.current = cy;
    setBuilt((b) => b + 1);
    return () => { cy.destroy(); cyRef.current = null; };
  }, [g, theme, layout]);

  const runLayout = useCallback((name: LayoutName) => {
    if (name === layout) cyRef.current?.layout(layoutOptions(name, true)).run();
    else setLayout(name);
  }, [layout]);

  // ---- which elements show: the timeline step and the type filter
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !g) return;
    const fresh: cytoscape.NodeSingular[] = [];
    cy.batch(() => {
      cy.nodes(':childless').forEach((n) => {
        const s = steps.get(n.id()) ?? 0;
        const hide = s > step || hiddenTypes.has(n.data('type'));
        const wasHidden = n.hasClass('hidden');
        n.toggleClass('hidden', hide);
        if (!hide && wasHidden && s === step) fresh.push(n);
      });
    });
    cy.nodes('.zone').forEach((z) => { z.toggleClass('hidden', z.children(':childless').not('.hidden').length === 0); });
    fresh.forEach((n) => {
      n.addClass('fresh');
      setTimeout(() => n.removeClass('fresh'), 1400);
    });
  }, [g, step, hiddenTypes, steps, built]);

  // ---- lens, row, review filter and selection: light some nodes, fade the rest
  const litIds = useMemo(() => {
    if (!g) return null;
    if (factFocus) return new Set(nodesOfFact(g, factFocus));
    if (lens && rowIdx !== null) return new Set(lens.rows[rowIdx].nodes);
    if (lens) return new Set(lens.rows.flatMap((r) => r.nodes));
    if (reviewFilter) return new Set(g.nodes.filter((n) => nodeReview(n) === reviewFilter).map((n) => n.id));
    return null;
  }, [g, lens, rowIdx, reviewFilter, factFocus]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass('faded hl');
      cy.nodes().unselect();
      cy.nodes('.zone').removeClass('dim');
      if (litIds) {
        cy.nodes(':childless').forEach((n) => { n.toggleClass('faded', !litIds.has(n.id())); });
        cy.nodes('.zone').forEach((z) => { z.toggleClass('dim', !z.children().toArray().some((c) => litIds.has(c.id()))); });
        cy.edges().forEach((e) => {
          const both = litIds.has(e.source().id()) && litIds.has(e.target().id());
          e.toggleClass('faded', !both);
          e.toggleClass('hl', both);
        });
      }
      if (selected) {
        const n = cy.$id(selected);
        n.select();
        n.removeClass('faded');
        n.connectedEdges().removeClass('faded').addClass('hl');
        n.neighborhood('node').removeClass('faded');
      }
    });
    const target = selected
      ? cy.$id(selected).closedNeighborhood().filter((e) => !e.hasClass('hidden'))
      : litIds ? cy.nodes(':childless').filter((n) => litIds.has(n.id()) && !n.hasClass('hidden')) : null;
    if (target && target.length > 0) {
      // fit the lit nodes, but never closer than 1.25x, so a small group keeps its surroundings
      const bb = target.boundingBox();
      const pad = selected ? 120 : 70;
      const zoom = Math.min(1.25, (cy.width() - 2 * pad) / Math.max(bb.w, 1), (cy.height() - 2 * pad - 90) / Math.max(bb.h, 1));
      cy.animate({ zoom, center: { eles: target } }, { duration: 650, easing: 'ease-in-out-cubic' });
    }
  }, [litIds, selected, built, g]);

  // ---- timeline playback
  useEffect(() => {
    if (!playing) return;
    if (step >= lastStep) { setPlaying(false); return; }
    const t = setTimeout(() => setStep((s) => s + 1), 1700);
    return () => clearTimeout(t);
  }, [playing, step, lastStep]);

  // ---- asking the graph
  const hits = useMemo(() => (g && query.trim() ? ask(g, query) : []), [g, query]);
  const choose = (h: Hit) => {
    setAskOpen(false);
    setFactFocus(null);
    setReviewFilter(null);
    if (h.kind === 'lens') { setLensKey(h.lens!); setRowIdx(null); setSelected(null); }
    if (h.kind === 'row') { setLensKey(h.lens!); setRowIdx(h.row!); setSelected(null); }
    if (h.kind === 'node') { setSelected(h.node!); }
    if (h.kind === 'fact') { setSelected(null); setLensKey(null); setFactFocus(h.fact!); }
    setStep(lastStep);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && document.activeElement === document.body)) {
        e.preventDefault();
        askRef.current?.focus();
        setAskOpen(true);
      }
      if (e.key === 'Escape') { setAskOpen(false); setSelected(null); setFactFocus(null); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of g?.nodes ?? []) c[n.type] = (c[n.type] ?? 0) + 1;
    return c;
  }, [g]);
  const reviewCounts = useMemo(() => {
    const c = { needs_review: 0, settled: 0, not_final: 0 };
    for (const n of g?.nodes ?? []) { const r = nodeReview(n); if (r) c[r] += 1; }
    return c;
  }, [g]);

  if (error) return <div className="gp-error">{error}</div>;
  if (!g) return <div className="gp-loading"><span className="spinner" />Loading the deal graph…</div>;

  const placed = Object.values(g.facts).filter((f) => f.used).length;
  const total = Object.keys(g.facts).length;
  const node = selected ? byId.get(selected) ?? null : null;
  const newAtStep = g.nodes.filter((n) => steps.get(n.id) === step).length;

  const openNode = (id: string) => { setSelected(id); setFactFocus(null); };
  const chip = (factId: string, key?: string) => (
    <button key={key ?? factId} className="src" type="button"
      onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setPop({ id: factId, x: r.left, y: r.bottom }); }}
      onMouseLeave={() => setPop(null)}
      onClick={() => { setFactFocus(factId); setSelected(null); setLensKey(null); setPop(null); }}>
      <Icon name="quote" size={11} />{sourceLabel(g, factId)}
    </button>
  );
  const sources = (ids: string[]) => {
    const uniq = [...new Set(ids)].filter((id) => (g.facts[id]?.step ?? 0) <= step);
    return uniq.length ? <div className="srcs">{uniq.slice(0, 4).map((id) => chip(id))}{uniq.length > 4 && <span className="more">+{uniq.length - 4}</span>}</div> : null;
  };

  // ---------------------------------------------------------------- right panel content
  let panel: ReactNode;
  if (node) {
    panel = <Inspector g={g} n={node} step={step} sources={sources} openNode={openNode}
      back={() => setSelected(null)} backLabel={lens ? lens.title : factFocus ? 'Fact' : 'Overview'} />;
  } else if (factFocus) {
    const f = g.facts[factFocus];
    const ns = nodesOfFact(g, factFocus);
    panel = (
      <div className="pn-body">
        <button className="back" onClick={() => setFactFocus(null)}><Icon name="back" size={14} />Overview</button>
        <div className="eyebrow">Fact · {f.category}</div>
        <h2 className="pn-title">{f.text}</h2>
        <div className="meta">{sourceLabel(g, factFocus)}{f.section ? ` · ${f.section}` : ''}</div>
        {f.quote && <blockquote className="quote">“{f.quote}”</blockquote>}
        {f.flags.length > 0 && <div className="flags">{f.flags.map((fl) => <span key={fl} className="pill">{fl}</span>)}</div>}
        <h3 className="sec">Where it sits in the graph</h3>
        {ns.length === 0 && <p className="muted">Not placed: a pointer or filler line.</p>}
        <div className="links">{ns.map((id) => <NodeChip key={id} g={g} id={id} onClick={openNode} />)}</div>
      </div>
    );
  } else if (lens) {
    panel = (
      <div className="pn-body">
        <button className="back" onClick={() => { setLensKey(null); setRowIdx(null); }}><Icon name="back" size={14} />Overview</button>
        <div className="eyebrow"><Icon name={lens.icon} size={13} />Graph view of a summary</div>
        <h2 className="pn-title">{lens.title}</h2>
        <p className="muted">Each row is answered by the nodes it lights up. Click a row to focus it; click a node to see every value and its source.</p>
        <div className="rows">
          {lens.rows.map((r, i) => (
            <div key={r.row} className={`row ${rowIdx === i ? 'on' : ''}`} role="button" tabIndex={0}
              onClick={() => setRowIdx(rowIdx === i ? null : i)}
              onKeyDown={(e) => { if (e.key === 'Enter') setRowIdx(rowIdx === i ? null : i); }}>
              <div className="row-h">{r.row}</div>
              <div className="row-t">{r.text}</div>
              <div className="row-n">
                {r.nodes.map((id) => <NodeChip key={id} g={g} id={id} small onClick={(x) => { openNode(x); }} />)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  } else {
    const groups: Exclude<Review, null>[] = ['needs_review', 'not_final', 'settled'];
    panel = (
      <div className="pn-body">
        <div className="eyebrow"><Icon name="sparkle" size={13} />Built from labelled facts, no model call</div>
        <h2 className="pn-title">{g.bid.name}</h2>
        <div className="stats">
          <div className="stat"><b>{g.nodes.length}</b><span>nodes</span></div>
          <div className="stat"><b>{g.links.length}</b><span>links</span></div>
          <div className="stat"><b>{Object.keys(g.types).length}</b><span>types</span></div>
          <div className="stat warn"><b>{reviewCounts.needs_review}</b><span>need a person</span></div>
        </div>
        <div className="coverage">
          <div className="cov-h"><span>Facts placed in the graph</span><b>{placed} / {total}</b></div>
          <div className="bar"><i style={{ width: `${(100 * placed) / total}%` }} /></div>
        </div>
        <h3 className="sec">Documents, in issue order</h3>
        <ol className="docs">
          {g.documents.map((d) => (
            <li key={d.no} className={d.step <= step ? 'in' : ''}>
              <span className="doc-dot" /><b>{d.name}</b><span className="muted">{d.issued}</span>
              <span className="muted right">{Object.values(g.facts).filter((f) => f.doc === d.no).length} facts</span>
            </li>
          ))}
        </ol>
        {groups.map((r) => {
          const list = g.nodes.filter((n) => nodeReview(n) === r && (steps.get(n.id) ?? 0) <= step);
          if (list.length === 0) return null;
          return (
            <div key={r}>
              <h3 className="sec"><span className={`dot rv-${r}`} />{REVIEW_TEXT[r]} <span className="muted">{list.length}</span></h3>
              <div className="review">
                {list.map((n) => {
                  const f = n.fields.find((x) => x.status !== 'none') ?? n.fields[0];
                  return (
                    <button key={n.id} className="rv-item" onClick={() => openNode(n.id)}>
                      <TypeShape color={g.types[n.type].color} />
                      <span className="rv-l">{n.label}</span>
                      {f && <span className="rv-r">{f.reason || f.value}</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  const hoverNode = hover ? byId.get(hover.id) : null;
  const popFact = pop ? g.facts[pop.id] : null;

  return (
    <div className="gp">
      {/* ---------------------------------------------------------------- top bar */}
      <header className="gp-top">
        <div className="brand">
          <span className="logo"><Icon name="link" size={16} /></span>
          <div><div className="brand-t">Deal graph</div><div className="brand-s">{g.bid.name}</div></div>
        </div>
        <div className="ask">
          <Icon name="search" size={16} />
          <input ref={askRef} value={query} placeholder="Ask the graph: who decides, insurance limits, when is pricing due…"
            onFocus={() => setAskOpen(true)} onBlur={() => setTimeout(() => setAskOpen(false), 150)}
            onChange={(e) => { setQuery(e.target.value); setAskOpen(true); setAskIdx(0); }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setAskIdx((i) => Math.min(i + 1, hits.length - 1)); }
              if (e.key === 'ArrowUp') { e.preventDefault(); setAskIdx((i) => Math.max(i - 1, 0)); }
              if (e.key === 'Enter' && hits[askIdx]) { choose(hits[askIdx]); (e.target as HTMLInputElement).blur(); }
            }} />
          <kbd>Ctrl K</kbd>
          {askOpen && (
            <div className="ask-pop">
              {!query.trim() && (
                <>
                  <div className="ask-h">Try</div>
                  {['Who decides?', 'When is refined pricing due?', 'Insurance limits', 'What could get us rejected?', 'Utility billing'].map((s) => (
                    <button key={s} className="ask-i" onMouseDown={(e) => { e.preventDefault(); setQuery(s); }}>
                      <Icon name="sparkle" size={14} /><span>{s}</span>
                    </button>
                  ))}
                </>
              )}
              {query.trim() && hits.length === 0 && <div className="ask-empty">Nothing in the graph matches that.</div>}
              {hits.map((h, i) => (
                <button key={`${h.kind}${h.label}${i}`} className={`ask-i ${i === askIdx ? 'on' : ''}`}
                  onMouseDown={(e) => { e.preventDefault(); choose(h); }} onMouseEnter={() => setAskIdx(i)}>
                  <span className={`kind k-${h.kind}`}>{{ row: 'Answer', lens: 'View', node: 'Node', fact: 'Fact' }[h.kind]}</span>
                  <span className="ask-l"><b>{h.label}</b><span>{h.detail}</span></span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="top-r">
          <div className="seg">
            <button className={layout === 'zones' ? 'on' : ''} onClick={() => runLayout('zones')} title="Grouped into zones"><Icon name="fit" />Zones</button>
            <button className={layout === 'force' ? 'on' : ''} onClick={() => runLayout('force')} title="Force layout"><Icon name="shuffle" />Force</button>
            <button className={layout === 'rings' ? 'on' : ''} onClick={() => runLayout('rings')} title="Rings around the deal"><Icon name="rings" />Rings</button>
          </div>
          <button className="iconbtn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Light or dark">
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          </button>
        </div>
      </header>

      {/* ---------------------------------------------------------------- left rail */}
      <aside className="gp-left">
        <h3 className="sec">Summaries as graph views</h3>
        <nav className="lenses">
          {g.lenses.map((l) => (
            <button key={l.key} className={`lens ${lensKey === l.key ? 'on' : ''}`}
              onClick={() => { setLensKey(lensKey === l.key ? null : l.key); setRowIdx(null); setSelected(null); setReviewFilter(null); setFactFocus(null); }}>
              <Icon name={l.icon} /><span>{l.title}</span><span className="n">{l.rows.length}</span>
            </button>
          ))}
        </nav>
        <h3 className="sec">Review</h3>
        <div className="lenses">
          {(['needs_review', 'not_final', 'settled'] as const).map((r) => (
            <button key={r} className={`lens ${reviewFilter === r ? 'on' : ''}`}
              onClick={() => { setReviewFilter(reviewFilter === r ? null : r); setLensKey(null); setSelected(null); setFactFocus(null); }}>
              <span className={`dot rv-${r}`} /><span>{REVIEW_TEXT[r]}</span><span className="n">{reviewCounts[r]}</span>
            </button>
          ))}
        </div>
        <h3 className="sec">Node types
          {hiddenTypes.size > 0 && <button className="link" onClick={() => setHiddenTypes(new Set())}>Show all</button>}
        </h3>
        <div className="types">
          {Object.entries(g.types).filter(([k]) => counts[k]).map(([k, t]) => (
            <button key={k} className={`type ${hiddenTypes.has(k) ? 'off' : ''}`}
              onClick={() => setHiddenTypes((s) => { const x = new Set(s); if (x.has(k)) x.delete(k); else x.add(k); return x; })}>
              <TypeShape color={t.color} /><span>{t.name}</span><span className="n">{counts[k]}</span>
              <Icon name={hiddenTypes.has(k) ? 'eyeoff' : 'eye'} size={13} />
            </button>
          ))}
        </div>
      </aside>

      {/* ---------------------------------------------------------------- canvas */}
      <main className="gp-canvas">
        <div ref={boxRef} className="cy" />
        {hoverNode && (
          <div className="hovercard" style={{ left: hover!.x, top: hover!.y }}>
            <div className="hc-t"><TypeShape color={g.types[hoverNode.type].color} />{g.types[hoverNode.type].name}<ReviewPill review={nodeReview(hoverNode)} /></div>
            <b>{hoverNode.label}</b>
            {hoverNode.sub && <div className="muted">{hoverNode.sub}</div>}
            {hoverNode.fields.slice(0, 2).map((f) => {
              const v = fieldAt(g, f, step);
              return v ? <div key={f.name} className="hc-f"><span>{f.name}</span>{v.value}</div> : null;
            })}
          </div>
        )}
        <div className="zoom">
          <button onClick={() => cyRef.current?.animate({ zoom: (cyRef.current.zoom() * 1.3), center: { eles: cyRef.current.nodes(':selected') } }, { duration: 200 })} title="Zoom in"><Icon name="plus" /></button>
          <button onClick={() => cyRef.current?.animate({ zoom: cyRef.current.zoom() / 1.3 }, { duration: 200 })} title="Zoom out"><Icon name="minus" /></button>
          <button onClick={() => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(':visible'), padding: 40 } }, { duration: 400 })} title="Fit"><Icon name="fit" /></button>
        </div>
        <div className="legend">
          <span><i className="lg rv-needs_review" />Needs a person</span>
          <span><i className="lg rv-settled" />Settled by ranking</span>
          <span><i className="lg dashed" />Not final</span>
          <span><i className="lg faded" />Ruled out</span>
        </div>

        {/* ---------------------------------------------------------------- timeline */}
        <div className="timeline">
          <button className="play" onClick={() => { if (step >= lastStep) setStep(0); setPlaying(!playing); }} title="Replay documents in issue order">
            <Icon name={playing ? 'pause' : 'play'} size={14} />
          </button>
          <div className="track">
            <div className="track-fill" style={{ width: `${(100 * step) / Math.max(1, lastStep)}%` }} />
            {g.documents.map((d) => (
              <button key={d.no} className={`station ${d.step <= step ? 'in' : ''} ${d.step === step ? 'cur' : ''}`}
                style={{ left: `${(100 * d.step) / Math.max(1, lastStep)}%` }} onClick={() => { setPlaying(false); setStep(d.step); }}>
                <span className="st-dot" />
                <span className="st-l"><b>{d.name}</b><span>{d.issued}</span></span>
              </button>
            ))}
          </div>
          <div className="tl-note">+{newAtStep} nodes from <b>{g.documents[step]?.name}</b></div>
        </div>
      </main>

      {/* ---------------------------------------------------------------- right panel */}
      <aside className="gp-right">{panel}</aside>

      {popFact && pop && (
        <div className="factpop" style={{ left: Math.min(pop.x, window.innerWidth - 340), top: pop.y + 6 }}>
          <div className="fp-h">{sourceLabel(g, pop.id)}{popFact.section ? ` · ${popFact.section}` : ''}</div>
          <div className="fp-t">{popFact.text}</div>
          {popFact.quote && popFact.quote !== popFact.text && <div className="fp-q">“{popFact.quote.slice(0, 220)}”</div>}
        </div>
      )}
    </div>
  );
}

function NodeChip({ g, id, onClick, small, edge }: { g: Graph; id: string; onClick: (id: string) => void; small?: boolean; edge?: string }) {
  const n = g.nodes.find((x) => x.id === id);
  if (!n) return null;
  return (
    <button className={`nchip ${small ? 'sm' : ''} ${n.status === 'removed' ? 'gone' : ''}`} onClick={(e) => { e.stopPropagation(); onClick(id); }}>
      {edge && <span className="edge">{edge}</span>}
      <TypeShape color={g.types[n.type].color} size={8} />{n.label}
    </button>
  );
}

function Inspector({ g, n, step, sources, openNode, back, backLabel }: {
  g: Graph; n: GNode; step: number; sources: (ids: string[]) => ReactNode; openNode: (id: string) => void;
  back: () => void; backLabel: string;
}) {
  const t = g.types[n.type];
  // Only what the documents up to `step` say: links whose other end exists yet, and the review state then.
  const there = (id: string) => { const o = g.nodes.find((x) => x.id === id); return !!o && nodeStep(g, o) <= step; };
  const out = g.links.filter((l) => l.from === n.id && there(l.to));
  const inn = g.links.filter((l) => l.to === n.id && there(l.from));
  const facts = [...new Set(allFacts(n))].filter((id) => (g.facts[id]?.step ?? 0) <= step);
  const review = nodeReview({ ...n, fields: n.fields.flatMap((f) => { const v = fieldAt(g, f, step); return v ? [{ ...f, status: v.status }] : []; }) });
  const [showFacts, setShowFacts] = useState(false);
  useEffect(() => setShowFacts(false), [n.id]);
  return (
    <div className="pn-body">
      <button className="back" onClick={back}><Icon name="back" size={14} />{backLabel}</button>
      <div className="insp-h" style={{ ['--tc' as string]: t.color }}>
        <div className="eyebrow"><TypeShape color={t.color} />{t.name}</div>
        <h2 className="pn-title">{n.label}</h2>
        {n.sub && <div className="meta">{n.sub}</div>}
        <div className="flags">
          <ReviewPill review={review} />
          {n.status === 'tentative' && <span className="pill st-tentative">Tentative</span>}
          {n.status === 'removed' && <span className="pill gone">Ruled out</span>}
        </div>
        {n.note && <p className="muted">{n.note}</p>}
      </div>
      {n.fields.length === 0 && n.lists.length === 0 && <div className="fields">{sources(n.facts)}</div>}
      {n.fields.length > 0 && (
        <div className="fields">
          {n.fields.map((f) => {
            const v = fieldAt(g, f, step);
            if (!v) return null;
            return (
              <div key={f.name} className={`field st-b-${v.status}`}>
                <div className="f-h"><span>{f.name}</span><StatusPill status={v.status} /></div>
                <div className="f-v">{v.value}</div>
                {v.competing.map((c) => (
                  <div key={c.value} className="f-lost">
                    <span className="lost-v">{c.value}</span>{sources(c.facts)}
                  </div>
                ))}
                {v.status !== 'none' && f.reason && <div className="f-r"><Icon name="sparkle" size={12} />{f.reason}</div>}
                {sources(f.facts)}
              </div>
            );
          })}
        </div>
      )}
      {n.lists.map((l) => {
        const items = l.items.filter((i) => i.facts.some((id) => (g.facts[id]?.step ?? 0) <= step));
        return (
          <div key={l.name}>
            <h3 className="sec">{l.name} <span className="muted">{items.length}</span></h3>
            <ul className="items">
              {items.map((i) => <li key={i.value}><span>{i.value}</span>{sources(i.facts)}</li>)}
            </ul>
          </div>
        );
      })}
      {(out.length > 0 || inn.length > 0) && <h3 className="sec">Links <span className="muted">{out.length + inn.length}</span></h3>}
      <div className="links">
        {out.map((l, i) => <NodeChip key={`o${i}`} g={g} id={l.to} edge={`${l.edge} →`} onClick={openNode} />)}
        {inn.map((l, i) => <NodeChip key={`i${i}`} g={g} id={l.from} edge={`← ${l.edge}`} onClick={openNode} />)}
      </div>
      <h3 className="sec">
        <button className="link" onClick={() => setShowFacts(!showFacts)}>{showFacts ? 'Hide' : 'Show'} the {facts.length} facts behind this node</button>
      </h3>
      {showFacts && (
        <ul className="factlist">
          {facts.map((id) => (
            <li key={id}><div>{g.facts[id].text}</div><div className="muted">{sourceLabel(g, id)}</div></li>
          ))}
        </ul>
      )}
    </div>
  );
}
