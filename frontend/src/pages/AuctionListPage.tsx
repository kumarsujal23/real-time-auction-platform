import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/services/api";
import { StatusBadge } from "@/components/StatusBadge";
import type { AuctionListItem } from "@/types";

export function AuctionListPage() {
  const [auctions, setAuctions] = useState<AuctionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAuctions()
      .then(setAuctions)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading auctions...</p>;
  if (error) return <p className="error-text">{error}</p>;

  return (
    <div className="browse-page">
      <section className="page-intro">
        <div className="eyebrow">The open market</div>
        <h1>Find something worth bidding for.</h1>
        <p className="intro-copy">Explore thoughtfully listed items, follow the action in real time, and make your move before the clock runs out.</p>
      </section>
      <div className="market-stats">
        <div className="stat-chip"><strong>{auctions.length}</strong><span>auctions listed</span></div>
        <div className="stat-chip"><strong>{auctions.filter((auction) => auction.status === "active").length}</strong><span>live right now</span></div>
        <div className="stat-chip"><strong>{auctions.reduce((total, auction) => total + auction.bid_count, 0)}</strong><span>bids placed</span></div>
      </div>
      {auctions.length === 0 && <div className="empty-state"><h3>No auctions yet</h3><p style={{ color: "var(--muted)" }}>Be the first to bring something interesting to the market.</p></div>}
      <div className="grid">
        {auctions.map((auction) => (
          <Link to={`/auctions/${auction.id}`} key={auction.id} className="card auction-card" style={{ color: "inherit" }}>
            <div className="auction-card-head">
              <h3>{auction.title}</h3>
              <StatusBadge status={auction.status} />
            </div>
            <p className="description">
              {auction.description || "No description provided."}
            </p>
            <div className="auction-card-footer">
              <div><div className="price-label">Current bid</div><div className="price">₹{Number(auction.current_price).toLocaleString()}</div></div>
              <div className="card-meta">{auction.bid_count} bid{auction.bid_count === 1 ? "" : "s"}<br />ends {new Date(auction.end_time).toLocaleDateString()}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
