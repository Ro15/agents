import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useState } from "react";
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
              <Routes>
                <Route path="/" element={<Dashboard onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                <Route path="/plugins" element={<PluginCatalogPage />} />
                <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
                <Route path="/datasets" element={<DatasetsPage onOpenDatasetPicker={() => setShowDatasetPicker(true)} />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/insights" element={<InsightsPage />} />
              </Routes>
            </main>
            {datasetPicker}
          </div>
        </BrowserRouter>
      </ToastProvider>
    </AppStateProvider>
  );
}

const DatasetPickerController: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { activePlugin, activeDataset, datasetListsByPlugin, setActiveDataset } = useAppState();
  const list = datasetListsByPlugin[activePlugin] || [];

  return (
    <DatasetPickerModal
      open={open}
      onClose={onClose}
      plugin={activePlugin}
      datasets={list}
      activeDatasetId={activeDataset?.dataset_id}
      onSelect={(meta) => {
        setActiveDataset(meta);
        onClose();
      }}
    />
  );
};

export default App;
