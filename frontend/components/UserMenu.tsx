"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Avatar from "./Avatar";
import { useAuth } from "./AuthProvider";
import { Icon } from "./Icon";

/** "Log in / Sign up" when signed out; an avatar with a profile menu when signed in. */
export default function UserMenu({ compact = false }: { compact?: boolean }) {
  const { user, loading, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (loading) return <span className="user-menu-skeleton" aria-hidden="true" />;

  if (!user) {
    return (
      <div className="auth-links">
        <Link href="/login" className="btn btn-sm btn-ghost">{compact ? <Icon name="user" size={16} /> : null}Log in</Link>
        {!compact && <Link href="/signup" className="btn btn-sm btn-primary">Sign up</Link>}
      </div>
    );
  }

  return (
    <div className="user-menu" ref={box}>
      <button className="avatar-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        title={`Signed in as ${user.name}`}>
        <Avatar user={user} />
        {!compact && <span className="avatar-name">{user.name.split(" ")[0]}</span>}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <strong>{user.name}</strong>
            <span className="tiny muted">{user.email}</span>
          </div>
          <Link role="menuitem" href="/profile" onClick={() => setOpen(false)}><Icon name="user" size={16} /> My profile</Link>
          <Link role="menuitem" href="/profile?tab=trips" onClick={() => setOpen(false)}>
            <Icon name="bookmark" size={16} /> Saved trips <span className="menu-count">{user.trip_count}</span>
          </Link>
          {user.is_admin && (
            <Link role="menuitem" href="/admin" onClick={() => setOpen(false)}><Icon name="layers" size={16} /> Admin panel</Link>
          )}
          <button role="menuitem" onClick={async () => { setOpen(false); await logout(); router.push("/"); }}>
            <Icon name="logout" size={16} /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
