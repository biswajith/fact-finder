import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { defaultTheme, Provider, ToastContainer } from '@adobe/react-spectrum';
import { App } from './App';
import { IntakeProvider } from './store';
import './mock.css';

function Root() {
  return (
    <Provider theme={defaultTheme} colorScheme="light" locale="en-US" height="100%">
      <IntakeProvider>
        <App />
      </IntakeProvider>
      <ToastContainer />
    </Provider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
