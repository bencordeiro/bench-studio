import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import { Toast } from "@/components/ui";

type ToastKind = "info" | "error" | "success";
interface ToastState {
  message: string;
  kind: ToastKind;
  id: number;
}

const ToastCtx = createContext<(message: string, kind?: ToastKind) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastState[]>([]);
  const push = useCallback((message: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { message, kind, id }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div>
        {toasts.map((t, i) => (
          <div key={t.id} style={{ bottom: `${16 + i * 64}px` }} className="fixed right-4 z-50">
            <Toast message={t.message} kind={t.kind} onClose={() => setToasts((cur) => cur.filter((x) => x.id !== t.id))} />
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}
