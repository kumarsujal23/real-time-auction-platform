import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="navbar">
      <Link to="/" className="brand">
        🏷️ Auction Platform
      </Link>
      <nav>
        <Link to="/">Browse</Link>
        {user && <Link to="/seller">Seller Dashboard</Link>}
        {user && <Link to="/buyer">My Bids</Link>}
        {user ? (
          <>
            <span style={{ color: "var(--muted)", fontSize: "0.9rem" }}>{user.full_name}</span>
            <button
              className="btn secondary"
              onClick={() => {
                logout();
                navigate("/");
              }}
            >
              Log out
            </button>
          </>
        ) : (
          <>
            <Link to="/login">Log in</Link>
            <Link to="/register" className="btn">
              Sign up
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
