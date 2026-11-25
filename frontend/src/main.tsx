import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AdminPage } from "./components/AdminPage";
import { FlowPage } from "./components/FlowPage";
import "./styles.css";

/** Three views and no router library: the chat widget, the admin page at #/admin and the live flow dashboard at #/flow. */
function Root() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  if (hash === "#/flow") return <FlowPage />;
  return hash === "#/admin" ? <AdminPage /> : <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
