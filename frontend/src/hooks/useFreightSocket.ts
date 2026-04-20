"use client";

import { useEffect, useRef } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Matches API WorkflowEventRecord shape. */
export interface FreightWorkflowEventRecord {
  id: string;
  shipment_id: string;
  event_type: string;
  stage: string;
  payload: Record<string, unknown>;
  created_at: string;
}

/** Build ws:// or wss:// URL for /ws/events from NEXT_PUBLIC_API_URL. */
export function freightWebSocketUrl(): string {
  try {
    const u = new URL(API_URL.replace(/\/$/, ""));
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws/events";
    u.search = "";
    u.hash = "";
    return u.toString();
  } catch {
    return "ws://localhost:8000/ws/events";
  }
}

export interface FreightRealtimeHandlers {
  onOverviewStale: () => void;
  onShipmentUpdated: (shipmentId: string) => void;
  onWorkflowEvent: (payload: { shipment_id: string; event: FreightWorkflowEventRecord }) => void;
}

/**
 * Subscribes to Freight backend WebSocket (JSON text frames).
 * Envelope: v, type, ts; types: hello | heartbeat | workflow_event | overview_stale | shipment_updated.
 */
export function useFreightSocket(handlers: FreightRealtimeHandlers): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const clearReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const scheduleReconnect = () => {
      clearReconnect();
      if (cancelled) {
        return;
      }
      const delayMs = Math.min(30_000, 1000 * 2 ** attempt);
      attempt = Math.min(attempt + 1, 8);
      reconnectTimer = setTimeout(() => connect(), delayMs);
    };

    const connect = () => {
      if (cancelled) {
        return;
      }
      clearReconnect();
      try {
        socket = new WebSocket(freightWebSocketUrl());
      } catch {
        scheduleReconnect();
        return;
      }

      socket.onopen = () => {
        attempt = 0;
      };

      socket.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as {
            type?: string;
            shipment_id?: string;
            event?: FreightWorkflowEventRecord;
            reason?: string | null;
          };
          const h = handlersRef.current;
          if (msg.type === "heartbeat" || msg.type === "hello") {
            return;
          }
          if (msg.type === "overview_stale") {
            h.onOverviewStale();
            return;
          }
          if (msg.type === "shipment_updated" && msg.shipment_id) {
            h.onShipmentUpdated(msg.shipment_id);
            return;
          }
          if (msg.type === "workflow_event" && msg.shipment_id && msg.event) {
            h.onWorkflowEvent({ shipment_id: msg.shipment_id, event: msg.event });
          }
        } catch {
          /* ignore malformed frames */
        }
      };

      socket.onerror = () => {
        socket?.close();
      };

      socket.onclose = () => {
        socket = null;
        scheduleReconnect();
      };
    };

    connect();

    const onVisibility = () => {
      if (document.visibilityState === "visible" && (!socket || socket.readyState === WebSocket.CLOSED)) {
        attempt = 0;
        clearReconnect();
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      clearReconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      socket?.close();
    };
  }, []);
}
