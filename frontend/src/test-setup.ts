import "@testing-library/jest-dom/vitest";

// jsdom does not implement ResizeObserver; Recharts requires it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// jsdom does not implement EventSource.
class EventSourceStub {
  static instances: EventSourceStub[] = [];
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  constructor(public url: string) {
    EventSourceStub.instances.push(this);
  }
  close() {}
}
globalThis.EventSource = EventSourceStub as unknown as typeof EventSource;
