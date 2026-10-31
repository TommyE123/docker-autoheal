import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import App from "./App.jsx";
import "bootstrap/dist/css/bootstrap.min.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "./styles/App.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);

// registerType "autoUpdate": a new service worker activates immediately and
// reloads open pages, so installed clients pick up new frontend builds without
// clearing caches. The reload can discard unsaved form input; it only happens
// when a new build has been deployed.
registerSW({ immediate: true });
