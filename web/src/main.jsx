import React from 'react';
import ReactDOM from 'react-dom/client';
import * as reactRouter from 'react-router-dom';
const { BrowserRouter } = reactRouter;
import App from './App';
import { UserProvider } from './context/UserContext';
import { DialogProvider } from './context/DialogContext';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <UserProvider>
      <DialogProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </DialogProvider>
    </UserProvider>
  </React.StrictMode>
);
