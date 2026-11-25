import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { GraphPage } from './GraphPage';
import './graph.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GraphPage src="./graph/durham.graph.json" />
  </StrictMode>,
);
