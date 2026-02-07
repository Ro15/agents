import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Suspense, lazy, useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { ChatPage } from "./pages/Chat";
import { InsightsPage } from "./pages/Insights";
import { PluginCatalogPage } from "./pages/PluginCatalog";
import { PluginDetailPage } from "./pages/PluginDetail";
import { DatasetsPage } from "./pages/Datasets";
import { AppStateProvider, useAppState } from "./state";
import { ToastProvider } from "./components/Toast";
import { TopNav } from "./components/TopNav";
import { ContextHeader } from "./components/ContextHeader";
import { DatasetPickerModal } from "./components/DatasetPickerModal";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Skeleton } from "./components/Skeleton";

// Code-split heavier feature pages
const QueryHistoryPage = lazy(() => import("./pages/QueryHistory").then((m) => ({ default: m.QueryHistoryPage })));
const DashboardListPage = lazy(() => import("./pages/DashboardBuilder").then((m) => ({ default: m.DashboardListPage })));
const DashboardDetailPage = lazy(() => import("./pages/DashboardBuilder").then((m) => ({ default: m.DashboardDetailPage })));
const ConnectorsPage = lazy(() => import("./pages/Connectors").then((m) => ({ default: m.ConnectorsPage })));
const SchedulesPage = lazy(() => import("./pages/Schedules").then((m) => ({ default: m.SchedulesPage })));
const DataCatalogPage = lazy(() => import("./pages/DataCatalog").then((m) => ({ default: m.DataCatalogPage })));
const UsagePage = lazy(() => import("./pages/Usage").then((m) => ({ default: m.UsagePage })));

const PageFallback = () => (
  <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
    <Skeleton className="h-10 w-48" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
);

function App() {
  const [showDatasetPicker, setShowDatasetPicker] = useState(false);

  const datasetPicker = <DatasetPickerController open={showDatasetPicker} onClose={() => setShowDatasetPicker(false)} />;

  return (
    <AppStateProvider>
      <ToastProvider>
        <BrowserRouter>
          <div className="min-h-screen bg-slate-50 text-slate-900">
            <TopNav />
            <ContextHeader onChangeDataset={() => setShowDatasetPicker(true)} />
            <main className="pb-16">
              <ErrorBoundary>
                <Suspense fallback={<PageFallback />}>
                  <Routes>
                    <Route path="/" element={<Dashboard onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                    <Route path="/plugins" element={<PluginCatalogPage />} />
                    <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
                    <Route path="/datasets" element={<DatasetsPage onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="/insights" element={<InsightsPage />} />
                    {/* Code-split feature routes */}
                    <Route path="/history" element={<QueryHistoryPage />} />
                    <Route path="/dashboards" element={<DashboardListPage />} />
                    <Route path="/dashboards/:dashboardId" element={<DashboardDetailPage />} />
                    <Route path="/connectors" element={<ConnectorsPage />} />
                    <Route path="/schedules" element={<SchedulesPage />} />
                    <Route path="/catalog" element={<DataCatalogPage />} />
                    <Route path="/usage" element={<UsagePage />} />
                  </Routes>
                </Suspense>
              </ErrorBoundary>
            </main>
            {datasetPicker}
          </div>
        </BrowserRouter>
      </ToastProvider>
    </AppStateProvider>
  );
}

const DatasetPickerController: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { activePlugin, activeDataset, datasetListsByPlugin, setActiveDataset, setActiveDatasetId } = useAppState();
  const list = datasetListsByPlugin[activePlugin] || [];

  return (
    <DatasetPickerModal
      open={open}
      onClose={onClose}
      plugin={activePlugin}
      datasets={list}
      activeDatasetId={activeDataset?.dataset_id}
      onSelect={(meta) => {
        if (meta) {
          setActiveDataset(meta);
        } else {
          setActiveDatasetId(null);
        }
        onClose();
      }}
    />
  );
};

export default App;
