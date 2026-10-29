"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { recordVisit } from "@/lib/admin";

/** Records each page view for the admin panel. Admin pages themselves aren't counted. */
export default function VisitTracker() {
  const path = usePathname();
  useEffect(() => {
    if (path && !path.startsWith("/admin")) recordVisit(path);
  }, [path]);
  return null;
}
