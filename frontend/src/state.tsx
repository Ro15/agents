import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from "react";
import type { DatasetMeta } from "./types";

type AppStateShape = {
  activePlugin: string;
  setActivePlugin: (p: string) => void;
  activeDatasetId: string | null;
  setActiveDatasetId: (id: string | null) => void;
  datasetListsByPlugin: Record<string, DatasetMeta[]>;
  setDatasetListForPlugin: (plugin: string, list: DatasetMeta[]) => void;
  upsertDatasetForPlugin: (plugin: string, meta: DatasetMeta) => void;
  deleteDatasetForPlugin: (plugin: string, datasetId: string) => void;
};

const AppStateContext = createContext<AppStateShape | undefined>(undefined);

const STORAGE_KEY = "plugin-dataset-map";
const PLUGIN_KEY = "active-plugin";
const DATASET_LIST_KEY = "dataset-lists-by-plugin";
const ACTIVE_DATASET_KEY = "active-dataset-by-plugin";

export const AppStateProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activePlugin, setActivePluginState] = useState<string>(() => {
    return localStorage.getItem(PLUGIN_KEY) || "retail";
  });
  const [datasetListsByPlugin, setDatasetListsByPlugin] = useState<Record<string, DatasetMeta[]>>(() => {
    const raw = localStorage.getItem(DATASET_LIST_KEY);
    return raw ? JSON.parse(raw) : {};
  });
  const [activeDatasetIdByPlugin, setActiveDatasetIdByPlugin] = useState<Record<string, string | null>>(() => {
    const raw = localStorage.getItem(ACTIVE_DATASET_KEY);
    return raw ? JSON.parse(raw) : {};
  });

  const setActivePlugin = useCallback((plugin: string) => {
    setActivePluginState(plugin);
    localStorage.setItem(PLUGIN_KEY, plugin);
  }, []);

  const setDatasetListForPlugin = useCallback(
    (plugin: string, list: DatasetMeta[]) => {
      setDatasetListsByPlugin((prev) => {
        const next = { ...prev, [plugin]: list };
        localStorage.setItem(DATASET_LIST_KEY, JSON.stringify(next));
        return next;
      });
      setActiveDatasetIdByPlugin((prev) => {
        const active = prev[plugin];
        if (active && !list.find((d) => d.dataset_id === active)) {
          const nextActive = { ...prev, [plugin]: list[0]?.dataset_id || null };
          localStorage.setItem(ACTIVE_DATASET_KEY, JSON.stringify(nextActive));
          return nextActive;
        }
        return prev;
      });
    },
    []
  );

  const upsertDatasetForPlugin = useCallback(
    (plugin: string, meta: DatasetMeta) => {
      setDatasetListsByPlugin((prev) => {
        const current = prev[plugin] || [];
        const nextList = [meta, ...current.filter((d) => d.dataset_id !== meta.dataset_id)];
        const next = { ...prev, [plugin]: nextList };
        localStorage.setItem(DATASET_LIST_KEY, JSON.stringify(next));
        return next;
      });
      setActiveDatasetIdByPlugin((prev) => {
        const next = { ...prev, [plugin]: meta.dataset_id };
        localStorage.setItem(ACTIVE_DATASET_KEY, JSON.stringify(next));
        return next;
      });
    },
    []
  );

  const deleteDatasetForPlugin = useCallback(
    (plugin: string, datasetId: string) => {
      setDatasetListsByPlugin((prev) => {
        const current = prev[plugin] || [];
        const nextList = current.filter((d) => d.dataset_id !== datasetId);
        const next = { ...prev, [plugin]: nextList };
        localStorage.setItem(DATASET_LIST_KEY, JSON.stringify(next));
        return next;
      });
      setActiveDatasetIdByPlugin((prev) => {
        const next = { ...prev };
        if (prev[plugin] === datasetId) {
          next[plugin] = null;
        }
        localStorage.setItem(ACTIVE_DATASET_KEY, JSON.stringify(next));
        return next;
      });
    },
    []
  );

  const activeDatasetId = activeDatasetIdByPlugin[activePlugin] || null;
  const activeDataset =
    (datasetListsByPlugin[activePlugin] || []).find((d) => d.dataset_id === activeDatasetId) || null;

  const value = useMemo(
    () => ({
      activePlugin,
      setActivePlugin,
      activeDataset,
      activeDatasetId,
      setActiveDatasetId: (id: string | null) =>
        setActiveDatasetIdByPlugin((prev) => {
          const next = { ...prev, [activePlugin]: id };
          localStorage.setItem(ACTIVE_DATASET_KEY, JSON.stringify(next));
          return next;
        }),
      datasetListsByPlugin,
      setDatasetListForPlugin,
      upsertDatasetForPlugin,
      deleteDatasetForPlugin,
    }),
    [activePlugin, activeDataset, activeDatasetId, datasetListsByPlugin]
  );

  useEffect(() => {
    // ensure active plugin key exists
    if (!(activePlugin in datasetListsByPlugin)) {
      setDatasetListForPlugin(activePlugin, []);
    }
    if (!(activePlugin in activeDatasetIdByPlugin)) {
      setActiveDatasetIdByPlugin((prev) => {
        const next = { ...prev, [activePlugin]: null };
        localStorage.setItem(ACTIVE_DATASET_KEY, JSON.stringify(next));
        return next;
      });
    }
  }, [activePlugin, datasetListsByPlugin, activeDatasetIdByPlugin, setDatasetListForPlugin]);

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
};

export const useAppState = () => {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState must be used within AppStateProvider");
  return ctx;
};
