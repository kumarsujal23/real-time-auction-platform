import { Route, Routes } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { RequireAuth } from "@/components/RequireAuth";
import { AuctionListPage } from "@/pages/AuctionListPage";
import { AuctionDetailPage } from "@/pages/AuctionDetailPage";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { SellerDashboard } from "@/pages/SellerDashboard";
import { BuyerDashboard } from "@/pages/BuyerDashboard";

export default function App() {
  return (
    <div className="app-shell">
      <Navbar />
      <Routes>
        <Route path="/" element={<AuctionListPage />} />
        <Route path="/auctions/:id" element={<AuctionDetailPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/seller"
          element={
            <RequireAuth>
              <SellerDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/buyer"
          element={
            <RequireAuth>
              <BuyerDashboard />
            </RequireAuth>
          }
        />
      </Routes>
    </div>
  );
}
