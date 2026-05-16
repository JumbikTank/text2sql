import { create } from 'zustand';
import type { TableInfo, TableDetails, TablePreviewResponse } from '@/types/schema';

interface SchemaState {
  tables: TableInfo[];
  selectedTable: string | null;
  selectedSchema: string;
  tableDetails: TableDetails | null;
  previewData: TablePreviewResponse | null;
  isLoadingTables: boolean;
  isLoadingDetails: boolean;
  isLoadingPreview: boolean;
  error: string | null;
  isSidebarOpen: boolean;

  // Actions
  setTables: (tables: TableInfo[]) => void;
  selectTable: (tableName: string | null) => void;
  setSelectedSchema: (schema: string) => void;
  setTableDetails: (details: TableDetails | null) => void;
  setPreviewData: (data: TablePreviewResponse | null) => void;
  setLoadingTables: (loading: boolean) => void;
  setLoadingDetails: (loading: boolean) => void;
  setLoadingPreview: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearError: () => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  reset: () => void;
}

const initialState = {
  tables: [],
  selectedTable: null,
  selectedSchema: 'public',
  tableDetails: null,
  previewData: null,
  isLoadingTables: false,
  isLoadingDetails: false,
  isLoadingPreview: false,
  error: null,
  isSidebarOpen: true,
};

export const useSchemaStore = create<SchemaState>()((set) => ({
  ...initialState,

  setTables: (tables) => set({ tables }),

  selectTable: (tableName) =>
    set({
      selectedTable: tableName,
      tableDetails: null,
      previewData: null,
    }),

  setSelectedSchema: (schema) =>
    set({
      selectedSchema: schema,
      tables: [],
      selectedTable: null,
      tableDetails: null,
      previewData: null,
    }),

  setTableDetails: (details) => set({ tableDetails: details }),

  setPreviewData: (data) => set({ previewData: data }),

  setLoadingTables: (loading) => set({ isLoadingTables: loading }),

  setLoadingDetails: (loading) => set({ isLoadingDetails: loading }),

  setLoadingPreview: (loading) => set({ isLoadingPreview: loading }),

  setError: (error) => set({ error }),

  clearError: () => set({ error: null }),

  toggleSidebar: () =>
    set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),

  setSidebarOpen: (open) => set({ isSidebarOpen: open }),

  reset: () => set(initialState),
}));
