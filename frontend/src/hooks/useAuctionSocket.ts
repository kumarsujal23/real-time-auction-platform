import { useEffect, useRef, useState } from "react";
import { wsUrlForAuction } from "@/services/api";
import type { AuctionSocketEvent } from "@/types";

/**
 * Subscribes to live updates for one auction over WebSocket.
 *
 * Reconnects automatically with a short backoff if the connection drops
 * (e.g. the backend restarts, or the load balancer recycles the
 * connection) - live auction data is exactly the kind of thing a user
 * should never have to manually refresh the page to get back.
 */
export function useAuctionSocket(auctionId: string | undefined) {
  const [lastEvent, setLastEvent] = useState<AuctionSocketEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    if (!auctionId) return;
    mountedRef.current = true;

    let attempt = 0;

    const connect = () => {
      const socket = new WebSocket(wsUrlForAuction(auctionId));
      socketRef.current = socket;

      socket.onopen = () => {
        attempt = 0;
        if (mountedRef.current) setConnected(true);
      };

      socket.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const parsed = JSON.parse(event.data) as AuctionSocketEvent;
          setLastEvent(parsed);
        } catch {
          // ignore malformed frames
        }
      };

      socket.onclose = () => {
        if (!mountedRef.current) return;
        setConnected(false);
        attempt += 1;
        const backoffMs = Math.min(1000 * 2 ** attempt, 10_000);
        reconnectTimeoutRef.current = setTimeout(connect, backoffMs);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      socketRef.current?.close();
    };
  }, [auctionId]);

  return { lastEvent, connected };
}
