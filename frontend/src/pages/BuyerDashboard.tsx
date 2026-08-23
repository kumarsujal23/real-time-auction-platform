import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/services/api";
import { StatusBadge } from "@/components/StatusBadge";
import type { AuctionListItem, AuctionStatus } from "@/types";

const TABS: { label: string; value: AuctionStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Scheduled", value: "scheduled" },
  { label: "Completed", value: "completed" },
];

export function BuyerDashboard() {
  const [tab, setTab] = useState<AuctionStatus | "all">("active");
  const [auctions, setAuctions] = useState<AuctionListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .listAuctions(tab === "all" ? {} : { status: tab })
      .then(setAuctions)
      .finally(() => setLoading(false));
  }, [tab]);

  return (
    <div>
      <h1>Browse Auctions</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {TABS.map((t) => (
          <button
            key={t.value}
            className={`btn ${tab === t.value ? "" : "secondary"}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p>Loading...</p>
      ) : auctions.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No auctions match this filter.</p>
      ) : (
        <div className="grid">
          {auctions.map((auction) => (
            <Link to={`/auctions/${auction.id}`} key={auction.id} className="card" style={{ color: "inherit" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <h3 style={{ margin: "0 0 8px" }}>{auction.title}</h3>
                <StatusBadge status={auction.status} />
              </div>
              <div className="price">₹{Number(auction.current_price).toLocaleString()}</div>
              <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: 6 }}>
                {auction.bid_count} bid{auction.bid_count === 1 ? "" : "s"} · click to view full bid history
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
