import { useEffect, useState } from "react";
import { api } from "@/services/api";

let globalTimeOffset = 0;
let hasFetchedOffset = false;

export function useCountdown(targetIso: string | undefined): string {
  const [label, setLabel] = useState("--:--:--");
  const [offset, setOffset] = useState(globalTimeOffset);

  useEffect(() => {
    if (!hasFetchedOffset) {
      hasFetchedOffset = true;
      api.getServerTime().then((res) => {
        globalTimeOffset = res.server_time_ms - Date.now();
        setOffset(globalTimeOffset);
      }).catch(() => {
        hasFetchedOffset = false; // Retry later if failed
      });
    } else {
      setOffset(globalTimeOffset);
    }
  }, []);

  useEffect(() => {
    if (!targetIso) return;
    const target = new Date(targetIso).getTime();

    const tick = () => {
      const now = Date.now() + offset;
      const diffMs = target - now;
      if (diffMs <= 0) {
        setLabel("Ended");
        return;
      }
      const totalSeconds = Math.floor(diffMs / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      const pad = (n: number) => n.toString().padStart(2, "0");
      setLabel(hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`);
    };

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [targetIso, offset]);

  return label;
}
