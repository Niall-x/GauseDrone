import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import "./index.css";
import { CapturesPage } from "./pages/CapturesPage";
import { NewRunPage } from "./pages/NewRunPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";

// The viewer pulls in three.js + Spark (~3 MB); load it only when opened.
const ViewerPage = lazy(() => import("./pages/ViewerPage").then((m) => ({ default: m.ViewerPage })));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* The viewer is full-screen, outside the app chrome. */}
        <Route path="/runs/:runId/view" element={<Suspense fallback={null}><ViewerPage /></Suspense>} />
        <Route element={<Layout />}>
          <Route index element={<RunsPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/captures" element={<CapturesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
