import type { AuctionStatus } from "@/types";

export function StatusBadge({ status }: { status: AuctionStatus }) {
  return <span className={`badge ${status}`}>{status}</span>;
}
