import os
import asyncio
import secrets
import httpx
from datetime import datetime
from typing import Optional

POLL_INTERVAL = 144 * 60  # 10 times per day


def _sb_headers() -> dict:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_url(path: str) -> str:
    return f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}"


async def _deactivate(sub_id: int, extra: dict = None):
    async with httpx.AsyncClient() as client:
        await client.patch(
            _sb_url("subscriptions"),
            params={"id": f"eq.{sub_id}"},
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            json={"active": False, **(extra or {})},
            timeout=10,
        )


async def create_subscription(
    name: str,
    email: str,
    appt_type: str,
    office_id: Optional[int] = None,
    office_name: Optional[str] = None,
    before_date: Optional[str] = None,
) -> dict:
    from dmv import check_office, search_offices, OFFICES

    async with httpx.AsyncClient() as client:
        params = {
            "email": f"eq.{email}",
            "appt_type": f"eq.{appt_type}",
            "active": "eq.true",
            "select": "id",
            "office_id": f"eq.{office_id}" if office_id is not None else "is.null",
        }
        check = await client.get(_sb_url("subscriptions"), params=params, headers=_sb_headers(), timeout=10)
        check.raise_for_status()
        if check.json():
            return check.json()[0]

        payload = {
            "name": name,
            "email": email,
            "appt_type": appt_type,
            "unsubscribe_token": secrets.token_hex(24),
            "active": True,
        }
        if office_id is not None:
            payload["office_id"] = office_id
        if office_name is not None:
            payload["office_name"] = office_name
        if before_date:
            payload["before_date"] = before_date

        r = await client.post(_sb_url("subscriptions"), headers=_sb_headers(), json=payload, timeout=10)
        r.raise_for_status()
        sub = r.json()[0]

    # Snapshot current earliest slot in the window so we only alert on improvement
    upper = datetime.fromisoformat(before_date).date() if before_date else None
    snapshot = None
    try:
        if office_id is not None:
            office = next((o for o in OFFICES if o["id"] == office_id), None)
            if office:
                result = await check_office(office, appt_type)
                dates = sorted(result["available_dates"])
                if upper:
                    dates = [d for d in dates if d.date() <= upper]
                snapshot = dates[0].isoformat() if dates else None
        else:
            results = await search_offices(appt_type)
            all_dates = sorted(d for r in results for d in r["available_dates"])
            if upper:
                all_dates = [d for d in all_dates if d.date() <= upper]
            snapshot = all_dates[0].isoformat() if all_dates else None
    except Exception:
        pass

    if snapshot is not None:
        async with httpx.AsyncClient() as client:
            await client.patch(
                _sb_url("subscriptions"),
                params={"id": f"eq.{sub['id']}"},
                headers={**_sb_headers(), "Prefer": "return=minimal"},
                json={"snapshot_slot": snapshot},
                timeout=10,
            )

    return sub


async def deactivate_subscription(token: str) -> bool:
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            _sb_url("subscriptions"),
            params={"unsubscribe_token": f"eq.{token}"},
            headers=_sb_headers(),
            json={"active": False},
            timeout=10,
        )
        r.raise_for_status()
        return len(r.json()) > 0


async def _send_slot_email(to: str, name: str, office_name: str, office_addr: str, appt_type: str, slot: datetime, token: str):
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
    booking_url = "https://coloradoappt.cxmflow.com/Appointment/Index/d74f48b1-33a9-428c-acd1-d7d1bfc9555c"
    unsub_url = f"{app_url}/api/unsubscribe?token={token}"
    slot_str = slot.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
    greeting = f"Hi {name}," if name else "Hi,"

    html_body = f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;color:#1a1a1a">
  <div style="background:#1a5fa8;border-radius:10px 10px 0 0;padding:20px 24px">
    <span style="color:#fff;font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Colorado DMV Finder</span>
  </div>
  <div style="border:1px solid #e5e5e5;border-top:none;border-radius:0 0 10px 10px;padding:24px">
    <p style="margin:0 0 16px;font-size:14px;color:#333">{greeting}</p>
    <h2 style="margin:0 0 6px;font-size:20px;color:#111">An earlier slot opened at {office_name}</h2>
    <p style="margin:0 0 20px;font-size:13px;color:#666">{appt_type}</p>
    <div style="background:#f7f7f5;border-radius:8px;padding:14px 16px;margin-bottom:20px">
      <p style="margin:0 0 4px;font-size:11px;color:#aaa;letter-spacing:1px;text-transform:uppercase">Earliest available</p>
      <p style="margin:0;font-size:16px;font-weight:600;color:#111">{slot_str}</p>
      <p style="margin:4px 0 0;font-size:12px;color:#888">{office_addr}</p>
    </div>
    <p style="margin:0 0 8px;font-size:13px;color:#555">
      On the DMV site, select <strong>{office_name}</strong> then <strong>{appt_type}</strong>.
    </p>
    <a href="{booking_url}"
       style="display:inline-block;background:#1a5fa8;color:#fff;text-decoration:none;padding:10px 20px;border-radius:8px;font-size:13.5px;font-weight:500;margin-top:12px">
      Book appointment →
    </a>
    <hr style="border:none;border-top:1px solid #ebebeb;margin:24px 0 16px">
    <p style="margin:0;font-size:11.5px;color:#bbb">
      You set up this alert on Colorado DMV Finder. Your alert is now removed.
      <a href="{unsub_url}" style="color:#999">Unsubscribe from future alerts</a>
    </p>
  </div>
</div>"""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json={
                "from": os.environ["RESEND_FROM_EMAIL"],
                "to": to,
                "subject": f"Earlier DMV slot at {office_name} — {slot_str}",
                "html": html_body,
            },
            timeout=15,
        )
        r.raise_for_status()


async def _send_expiry_email(to: str, name: str, office_name: Optional[str], appt_type: str, before_date: str, token: str):
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
    booking_url = "https://coloradoappt.cxmflow.com/Appointment/Index/d74f48b1-33a9-428c-acd1-d7d1bfc9555c"
    unsub_url = f"{app_url}/api/unsubscribe?token={token}"
    deadline = datetime.fromisoformat(before_date).strftime("%B %d, %Y")
    greeting = f"Hi {name}," if name else "Hi,"
    office_display = office_name if office_name else "any Colorado office"

    html_body = f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;color:#1a1a1a">
  <div style="background:#1a5fa8;border-radius:10px 10px 0 0;padding:20px 24px">
    <span style="color:#fff;font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Colorado DMV Finder</span>
  </div>
  <div style="border:1px solid #e5e5e5;border-top:none;border-radius:0 0 10px 10px;padding:24px">
    <p style="margin:0 0 16px;font-size:14px;color:#333">{greeting}</p>
    <h2 style="margin:0 0 6px;font-size:20px;color:#111">Your DMV slot alert has expired</h2>
    <p style="margin:0 0 20px;font-size:13px;color:#666">{appt_type} · {office_display}</p>
    <div style="background:#fff4e0;border-radius:8px;padding:14px 16px;margin-bottom:20px">
      <p style="margin:0;font-size:13.5px;color:#92580a">
        No earlier slots opened before your deadline of <strong>{deadline}</strong>. Your alert has been removed.
      </p>
    </div>
    <p style="margin:0 0 16px;font-size:13px;color:#555">
      If you still need an appointment, you can set up a new alert or check the DMV site directly.
    </p>
    <a href="{booking_url}"
       style="display:inline-block;background:#1a5fa8;color:#fff;text-decoration:none;padding:10px 20px;border-radius:8px;font-size:13.5px;font-weight:500">
      Check DMV availability →
    </a>
    <hr style="border:none;border-top:1px solid #ebebeb;margin:24px 0 16px">
    <p style="margin:0;font-size:11.5px;color:#bbb">
      <a href="{unsub_url}" style="color:#999">Unsubscribe from future alerts</a>
    </p>
  </div>
</div>"""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json={
                "from": os.environ["RESEND_FROM_EMAIL"],
                "to": to,
                "subject": f"Your DMV slot alert expired — no slots opened before {deadline}",
                "html": html_body,
            },
            timeout=15,
        )
        r.raise_for_status()


async def poll_and_notify():
    from dmv import check_office, search_offices, OFFICES

    async with httpx.AsyncClient() as client:
        r = await client.get(
            _sb_url("subscriptions"),
            params={"active": "eq.true", "select": "*"},
            headers=_sb_headers(),
            timeout=10,
        )
        r.raise_for_status()
        subs = r.json()

    if not subs:
        return

    today = datetime.utcnow().date()

    # Expire subscriptions whose before_date has passed
    expired = [s for s in subs if s.get("before_date") and datetime.fromisoformat(s["before_date"]).date() < today]
    active_subs = [s for s in subs if s["id"] not in {e["id"] for e in expired}]

    for sub in expired:
        try:
            await _send_expiry_email(
                to=sub["email"],
                name=sub.get("name", ""),
                office_name=sub.get("office_name"),
                appt_type=sub["appt_type"],
                before_date=sub["before_date"],
                token=sub["unsubscribe_token"],
            )
        except Exception:
            pass
        await _deactivate(sub["id"], {"notified_at": datetime.utcnow().isoformat()})

    # Group specific-office subs — one DMV hit per (office_id, appt_type) pair
    office_groups: dict[tuple, list] = {}
    anyoffice_groups: dict[str, list] = {}
    for s in active_subs:
        if s.get("office_id") is not None:
            office_groups.setdefault((s["office_id"], s["appt_type"]), []).append(s)
        else:
            anyoffice_groups.setdefault(s["appt_type"], []).append(s)

    for (office_id, appt_type), group in office_groups.items():
        office = next((o for o in OFFICES if o["id"] == office_id), None)
        if not office:
            continue
        try:
            result = await check_office(office, appt_type)
        except Exception:
            continue

        all_dates: list[datetime] = sorted(result["available_dates"])

        for sub in group:
            upper = datetime.fromisoformat(sub["before_date"]).date() if sub.get("before_date") else None
            matching = [d for d in all_dates if upper is None or d.date() <= upper]
            if not matching:
                continue

            earliest = matching[0]
            snapshot = datetime.fromisoformat(sub["snapshot_slot"]).replace(tzinfo=None) if sub.get("snapshot_slot") else None

            # Only fire when something earlier than the baseline opened up
            if snapshot is not None and earliest.replace(tzinfo=None) >= snapshot:
                continue

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
            except Exception:
                continue

            await _deactivate(sub["id"], {
                "notified_at": datetime.utcnow().isoformat(),
                "notified_slot": earliest.isoformat(),
            })

    for appt_type, group in anyoffice_groups.items():
        try:
            results = await search_offices(appt_type)
        except Exception:
            continue

        # Flat list of (datetime, office_name, office_addr) sorted earliest first
        all_slots: list[tuple] = sorted(
            (d, r["name"], r["address"])
            for r in results
            for d in r["available_dates"]
        )

        for sub in group:
            upper = datetime.fromisoformat(sub["before_date"]).date() if sub.get("before_date") else None
            matching = [(d, n, a) for d, n, a in all_slots if upper is None or d.date() <= upper]
            if not matching:
                continue

            earliest, office_name, office_addr = matching[0]
            snapshot = datetime.fromisoformat(sub["snapshot_slot"]).replace(tzinfo=None) if sub.get("snapshot_slot") else None

            if snapshot is not None and earliest.replace(tzinfo=None) >= snapshot:
                continue

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
            except Exception:
                continue

            await _deactivate(sub["id"], {
                "notified_at": datetime.utcnow().isoformat(),
                "notified_slot": earliest.isoformat(),
            })


async def run_poller():
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("RESEND_API_KEY"):
        return
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await poll_and_notify()
        except Exception:
            pass
