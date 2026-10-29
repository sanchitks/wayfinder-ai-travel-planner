"use client";

import { useState } from "react";
import { initials, type User } from "@/lib/auth";

/** The user's Google photo when there is one, otherwise their initials. */
export default function Avatar({ user, large = false }: { user: Pick<User, "name" | "avatar_url">; large?: boolean }) {
  const [broken, setBroken] = useState(false);
  const cls = `avatar${large ? " avatar-lg" : ""}`;
  if (user.avatar_url && !broken) {
    // Google's photo host can refuse requests that carry a referrer.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className={`${cls} avatar-img`} src={user.avatar_url} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} />;
  }
  return <span className={cls}>{initials(user.name)}</span>;
}
