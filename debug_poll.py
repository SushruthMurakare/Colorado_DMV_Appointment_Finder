"""
Run this to debug the notification poller step by step.
Usage: python debug_poll.py
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

import httpx
from datetime import datetime
from dmv import check_office, search_offices, OFFICES
from notifications import _sb_headers, _sb_url, _send_slot_email, _send_expiry_email


async def main():
    print("\n── Step 1: Fetch active subscriptions from Supabase ──")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _sb_url("subscriptions"),
            params={"active": "eq.true", "select": "*"},
            headers=_sb_headers(),
            timeout=10,
        )
        print(f"  Status: {r.status_code}")
        r.raise_for_status()
        subs = r.json()
        print(f"  Found {len(subs)} active subscription(s)")
        for s in subs:
            office = s.get("office_name") or "any office"
            print(f"    → {s['name']} | {s['email']} | office={office} | type={s['appt_type']} | before={s.get('before_date')} | snapshot={s.get('snapshot_slot')}")

    if not subs:
        print("\n  Nothing to do — no active subscriptions.")
        return

    today = datetime.utcnow().date()

    # ── Expiry check ──────────────────────────────────────────────────────────
    expired = [s for s in subs if s.get("before_date") and datetime.fromisoformat(s["before_date"]).date() < today]
    active_subs = [s for s in subs if s["id"] not in {e["id"] for e in expired}]

    if expired:
        print(f"\n── Expired subscriptions ({len(expired)}) ──")
        for sub in expired:
            print(f"  → {sub['email']} expired (before_date={sub['before_date']})")
            print(f"    Sending expiry email to {sub['email']}...")
            try:
                await _send_expiry_email(
                    to=sub["email"],
                    name=sub.get("name", ""),
                    office_name=sub.get("office_name"),
                    appt_type=sub["appt_type"],
                    before_date=sub["before_date"],
                    token=sub["unsubscribe_token"],
                )
                print(f"    ✓ Expiry email sent!")
            except Exception as e:
                print(f"    ✗ Email failed: {e}")

    # ── Group subs ────────────────────────────────────────────────────────────
    office_groups: dict[tuple, list] = {}
    anyoffice_groups: dict[str, list] = {}
    for s in active_subs:
        if s.get("office_id") is not None:
            office_groups.setdefault((s["office_id"], s["appt_type"]), []).append(s)
        else:
            anyoffice_groups.setdefault(s["appt_type"], []).append(s)

    # ── Specific-office subs ──────────────────────────────────────────────────
    for (office_id, appt_type), group in office_groups.items():
        office = next((o for o in OFFICES if o["id"] == office_id), None)
        if not office:
            print(f"\n  ✗ No office found with id={office_id}")
            continue

        print(f"\n── Check DMV: '{office['name']}' / '{appt_type}' ──")
        try:
            result = await check_office(office, appt_type)
        except Exception as e:
            print(f"  ✗ check_office raised: {e}")
            continue

        if not result["available_dates"]:
            print(f"  ✗ No available dates found")
            continue

        all_dates: list[datetime] = sorted(result["available_dates"])
        print(f"  ✓ Found {len(all_dates)} available slot(s):")
        for d in all_dates:
            print(f"    {d}")

        for sub in group:
            print(f"\n  Evaluating for {sub['email']}:")
            upper = datetime.fromisoformat(sub["before_date"]).date() if sub.get("before_date") else None
            matching = [d for d in all_dates if upper is None or d.date() <= upper]
            if not matching:
                print(f"    ✗ No slots within before_date window — skipping")
                continue

            earliest = matching[0]
            snapshot = datetime.fromisoformat(sub["snapshot_slot"]).replace(tzinfo=None) if sub.get("snapshot_slot") else None
            print(f"    Earliest in window : {earliest}")
            print(f"    Snapshot at signup : {snapshot}")

            if snapshot is not None and earliest.replace(tzinfo=None) >= snapshot:
                print(f"    ✗ No improvement over snapshot — skipping")
                continue

            print(f"    ✓ Earlier slot found! Sending email to {sub['email']}...")
            try:
                await _send_slot_email(
                    to=sub["email"],
                    name=sub.get("name", ""),
                    office_name=sub["office_name"],
                    office_addr=office["address"],
                    appt_type=appt_type,
                    slot=earliest,
                    token=sub["unsubscribe_token"],
                )
                print(f"    ✓ Email sent!")
            except Exception as e:
                print(f"    ✗ Email send failed: {e}")

    # ── Any-office subs ───────────────────────────────────────────────────────
    for appt_type, group in anyoffice_groups.items():
        print(f"\n── Check DMV (all offices): '{appt_type}' ──")
        try:
            results = await search_offices(appt_type)
        except Exception as e:
            print(f"  ✗ search_offices raised: {e}")
            continue

        all_slots: list[tuple] = sorted(
            (d, r["name"], r["address"])
            for r in results
            for d in r["available_dates"]
        )
        print(f"  ✓ Found {len(all_slots)} total slot(s) across all offices")

        for sub in group:
            print(f"\n  Evaluating for {sub['email']}:")
            upper = datetime.fromisoformat(sub["before_date"]).date() if sub.get("before_date") else None
            matching = [(d, n, a) for d, n, a in all_slots if upper is None or d.date() <= upper]
            if not matching:
                print(f"    ✗ No slots within before_date window — skipping")
                continue

            earliest, office_name, office_addr = matching[0]
            snapshot = datetime.fromisoformat(sub["snapshot_slot"]).replace(tzinfo=None) if sub.get("snapshot_slot") else None
            print(f"    Earliest in window : {earliest} @ {office_name}")
            print(f"    Snapshot at signup : {snapshot}")

            if snapshot is not None and earliest.replace(tzinfo=None) >= snapshot:
                print(f"    ✗ No improvement over snapshot — skipping")
                continue

            print(f"    ✓ Earlier slot found! Sending email to {sub['email']}...")
            try:
                await _send_slot_email(
                    to=sub["email"],
                    name=sub.get("name", ""),
                    office_name=office_name,
                    office_addr=office_addr,
                    appt_type=appt_type,
                    slot=earliest,
                    token=sub["unsubscribe_token"],
                )
                print(f"    ✓ Email sent!")
            except Exception as e:
                print(f"    ✗ Email send failed: {e}")

    print("\n── Done ──\n")


asyncio.run(main())
