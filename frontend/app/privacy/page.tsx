"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import ThemeSwitch from "@/components/ThemeSwitch";
import UserMenu from "@/components/UserMenu";
import { siteInfo } from "@/lib/auth";

const UPDATED = "30 October 2026";

export default function PrivacyPage() {
  const [info, setInfo] = useState<{ privacy_contact: string; visit_retention_days: number } | null>(null);
  useEffect(() => {
    siteInfo().then(setInfo);
  }, []);
  const contact = info?.privacy_contact;
  const days = info?.visit_retention_days ?? 365;

  return (
    <div className="profile-page">
      <header className="profile-topbar">
        <Link href="/" className="brand"><span className="brand-mark"><Icon name="compass" size={19} /></span> Wayfinder</Link>
        <div className="row" style={{ marginLeft: "auto", gap: 10 }}>
          <ThemeSwitch />
          <UserMenu compact />
        </div>
      </header>

      <main className="legal">
        <div className="eyebrow">Privacy</div>
        <h1 className="section-heading" style={{ marginBottom: 4 }}>Privacy <b>Policy</b></h1>
        <p className="small muted">Last updated {UPDATED}</p>

        <p>
          Wayfinder is an AI travel planner. This page explains, in plain words, what we collect when you use it, why, who else
          receives it, how long we keep it, and how you can see, correct, download or delete it.
        </p>

        <h2>What we collect</h2>
        <ul>
          <li><b>Your account.</b> Your name and email address. If you sign up with email, your password, which is stored only as a
            one-way hash (scrambled so that nobody, including us, can read it). If you sign in with Google, the name, email and
            profile photo that Google shares with us.</li>
          <li><b>Your profile (optional).</b> Phone number, home city, usual travel style and budget, food preferences, interests and a
            short &ldquo;about you&rdquo;, if you add them.</li>
          <li><b>Your trips.</b> The trips you plan while logged in: where, when, who&apos;s travelling, your budget and notes, and the
            itinerary we build.</li>
          <li><b>Page visits.</b> Which pages are opened and when, the type of device, browser and operating system, the website you came
            from, and your IP address with its last part hidden (for example 49.36.12.x). A random visitor ID in a cookie lets us
            count returning visitors. When you&apos;re logged in, your visits are linked to your account.</li>
        </ul>

        <h2>Why we use it</h2>
        <ul>
          <li>To plan your trips, save them, and fill in new trips from your profile.</li>
          <li>To keep your account secure, for example by keeping you logged in safely and slowing down repeated wrong passwords.</li>
          <li>To understand how Wayfinder is used (popular pages, devices and destinations) so we can improve it.</li>
        </ul>
        <p>We don&apos;t sell your data, we don&apos;t show ads, and we don&apos;t use your data to track you on other websites.</p>

        <h2>Cookies and storage on your device</h2>
        <div className="table-wrap card">
          <table className="data-table">
            <thead><tr><th>Name</th><th>What it&apos;s for</th><th>How long</th></tr></thead>
            <tbody>
              <tr><td><code>wf_session</code></td><td>Keeps you logged in. Your browser&apos;s scripts can&apos;t read it.</td><td>30 days, or until you log out</td></tr>
              <tr><td><code>wf_vid</code></td><td>A random visitor ID used to count visits.</td><td>1 year</td></tr>
              <tr><td><code>wf_oauth_state</code></td><td>Protects &ldquo;Continue with Google&rdquo; against forged sign-ins.</td><td>10 minutes</td></tr>
              <tr><td><code>wf-theme</code></td><td>Remembers light or dark mode (stored on your device only).</td><td>Until you clear it</td></tr>
              <tr><td><code>wf-pending-trip</code></td><td>Keeps a plan you made while logged out, so it can be saved after you log in.</td><td>Until you close the tab</td></tr>
            </tbody>
          </table>
        </div>

        <h2>Who else receives data</h2>
        <ul>
          <li><b>Google</b>, only if you choose &ldquo;Continue with Google&rdquo;, to confirm who you are.</li>
          <li><b>Travel and map services</b> receive the travel details needed to answer a search: cities, dates, number of travellers
            and places to route between. They don&apos;t receive your name or email. These are Ignav (flight fares), Xotelo and TripAdvisor
            (hotel prices), Wikipedia and Wikidata (sights), OpenStreetMap and Nominatim (places and restaurants), OSRM (road routes) and
            Esri (map images).</li>
          <li><b>AI model provider.</b> When the AI planner is switched on, your trip request and chat messages are sent to the AI service
            (Claude, through OpenRouter or Anthropic) to plan the trip. Please don&apos;t put sensitive personal information in your notes or
            messages.</li>
          <li>Booking links open the seller&apos;s own website (airline, IRCTC, Booking.com, Agoda and others). Anything you enter there is
            covered by their privacy policy, not this one.</li>
        </ul>

        <h2>How long we keep it</h2>
        <ul>
          <li>Your account, profile and saved trips: until you delete them or your account.</li>
          <li>Page-visit records: {days} days, then they&apos;re deleted automatically.</li>
          <li>If you delete your account, your profile, trips, login sessions and Google link are deleted straight away. Past page visits
            stay only as anonymous statistics, no longer linked to you.</li>
        </ul>

        <h2>How we protect it</h2>
        <p>
          Passwords are stored only as salted one-way hashes. Logins use a secure cookie that page scripts can&apos;t read. IP addresses are
          stored with their last part hidden. Only named administrators can see customer records, and even they can&apos;t see passwords.
        </p>

        <h2>Your rights</h2>
        <ul>
          <li><b>See and download your data:</b> <Link href="/profile?tab=security">Profile → Security → Download my data</Link>.</li>
          <li><b>Correct it:</b> edit your details any time in <Link href="/profile">your profile</Link>.</li>
          <li><b>Delete it:</b> delete single trips under Saved trips, or your whole account under Profile → Security.</li>
          <li><b>Withdraw consent:</b> delete your account, or simply stop using Wayfinder.</li>
          <li><b>Questions or complaints:</b> {contact
            ? <>write to <a href={`mailto:${contact}`}>{contact}</a>. We&apos;ll reply as soon as we can.</>
            : <>contact the Wayfinder team at the privacy email address that will be listed here.</>}</li>
        </ul>

        <h2>Age</h2>
        <p>Wayfinder accounts are for people aged 18 or over. If you&apos;re planning a family trip, a parent or guardian should create the account.</p>

        <h2>Changes to this policy</h2>
        <p>If we change how we use your data, we&apos;ll update this page and the date at the top.</p>
      </main>
    </div>
  );
}
