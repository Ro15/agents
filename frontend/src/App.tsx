import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { ChatPage } from "./pages/Chat";
import { InsightsPage } from "./pages/Insights";
import { PluginCatalogPage } from "./pages/PluginCatalog";
import { PluginDetailPage } from "./pages/PluginDetail";
import { DatasetsPage } from "./pages/Datasets";
import { ConnectorsPage } from "./pages/Connectors";
import { QueryHistoryPage } from "./pages/QueryHistory";
import { DashboardListPage } from "./pages/DashboardBuilder";
import { SchedulesPage } from "./pages/Schedules";
import { DataCatalogPage } from "./pages/DataCatalog";
import { UsagePage } from "./pages/Usage";
import { AppStateProvider, useAppState } from "./state";
import { ToastProvider } from "./components/Toast";
import { TopNav } from "./components/TopNav";
import { ContextHeader } from "./components/ContextHeader";
import { DatasetPickerModal } from "./components/DatasetPickerModal";
import { ErrorBoundary } from "./components/ErrorBoundary";

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
                  <Routes>
                    <Route path="/" element={<Dashboard onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                    <Route path="/plugins" element={<PluginCatalogPage />} />
                    <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
                    <Route path="/datasets" element={<DatasetsPage onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="/insights" element={<InsightsPage />} />
                    <Route path="/connectors" element={<ConnectorsPage />} />
                    <Route path="/history" element={<QueryHistoryPage />} />
                    <Route path="/dashboard-builder" element={<DashboardListPage />} />
                    <Route path="/schedules" element={<SchedulesPage />} />
                    <Route path="/catalog" element={<DataCatalogPage />} />
                    <Route path="/usage" element={<UsagePage />} />
                  </Routes>
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
