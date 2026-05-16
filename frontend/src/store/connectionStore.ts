import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { DatabaseConnectionConfig } from '@/types/schema';

interface ConnectionState {
  connections: DatabaseConnectionConfig[];
  activeConnectionId: string | null;
  isLoading: boolean;
  error: string | null;
  isModalOpen: boolean;
  editingConnection: DatabaseConnectionConfig | null;

  // Actions
  setConnections: (connections: DatabaseConnectionConfig[]) => void;
  addConnection: (connection: DatabaseConnectionConfig) => void;
  updateConnection: (id: string, connection: DatabaseConnectionConfig) => void;
  removeConnection: (id: string) => void;
  setActiveConnectionId: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearError: () => void;
  openModal: (connection?: DatabaseConnectionConfig) => void;
  closeModal: () => void;
}

export const useConnectionStore = create<ConnectionState>()(
  persist(
    (set) => ({
      connections: [],
      activeConnectionId: null,
      isLoading: false,
      error: null,
      isModalOpen: false,
      editingConnection: null,

      setConnections: (connections) =>
        set({ connections }),

      addConnection: (connection) =>
        set((state) => ({
          connections: [...state.connections, connection],
        })),

      updateConnection: (id, connection) =>
        set((state) => ({
          connections: state.connections.map((conn) =>
            conn.id === id ? connection : conn
          ),
        })),

      removeConnection: (id) =>
        set((state) => ({
          connections: state.connections.filter((conn) => conn.id !== id),
          activeConnectionId:
            state.activeConnectionId === id ? null : state.activeConnectionId,
        })),

      setActiveConnectionId: (id) =>
        set({ activeConnectionId: id }),

      setLoading: (loading) => set({ isLoading: loading }),

      setError: (error) => set({ error }),

      clearError: () => set({ error: null }),

      openModal: (connection) =>
        set({
          isModalOpen: true,
          editingConnection: connection || null,
        }),

      closeModal: () =>
        set({
          isModalOpen: false,
          editingConnection: null,
        }),
    }),
    {
      name: 'connection-storage',
      partialize: (state) => ({
        activeConnectionId: state.activeConnectionId,
      }),
    }
  )
);
