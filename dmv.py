#!/usr/bin/env python3
"""
Colorado DMV Appointment Finder
Can be used as a CLI or imported by api.py

CLI Usage:
  python dmv.py "Written Test"
  python dmv.py "Written Test" --office Adams --debug
"""

import sys
import re
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://coloradoappt.cxmflow.com/Appointment/Index/d74f48b1-33a9-428c-acd1-d7d1bfc9555c"

STEP_ID_LOCATION = "aedf3d01-fc4c-4770-b48e-b70d996f3640"
STEP_ID_SERVICE  = "284cca1d-9462-4b57-b6ba-7d069fcb335f"

TARGET_TYPE  = "OABSEngine.Step, OABSEngine, Version=2.30.73.1, Culture=neutral, PublicKeyToken=null"
CONTROL_TYPE = "OABSEngine.StepControl, OABSEngine, Version=2.30.73.1, Culture=neutral, PublicKeyToken=null"
MODEL_TYPE   = "OABSEngine.Models.QFlowObjectModel, OABSEngine, Version=2.30.73.1, Culture=neutral, PublicKeyToken=null"

OFFICES = [
    {"id": 81,  "name": "Adams",                         "address": "12200 N Pecos St Ste 100, Westminster"},
    {"id": 15,  "name": "Alamosa",                        "address": "702 Del Sol Dr, Alamosa"},
    {"id": 10,  "name": "Aurora",                         "address": "14391 E 4th Ave, Aurora"},
    {"id": 85,  "name": "Boulder",                        "address": "4800 Baseline Rd Suite A-102, Boulder"},
    {"id": 16,  "name": "Canon City",                     "address": "127 Justice Center Rd Ste K, Canon City"},
    {"id": 14,  "name": "Centennial",                     "address": "5120 E Arapahoe Rd, Centennial"},
    {"id": 19,  "name": "Colorado Springs",               "address": "2447 N Union Blvd, Colorado Springs"},
    {"id": 31,  "name": "Cortez",                         "address": "2210 E Main St, Cortez"},
    {"id": 32,  "name": "Craig",                          "address": "555 Breeze #130, Craig"},
    {"id": 45,  "name": "Delta",                          "address": "501 Palmer St Ste 210, Delta"},
    {"id": 12,  "name": "Denver NE",                      "address": "4685 Peoria St Ste 115, Denver"},
    {"id": 91,  "name": "Denver Regional",                "address": "1351 5th Street Suite 100, Denver"},
    {"id": 33,  "name": "Durango",                        "address": "329-A S Camino Del Rio, Durango"},
    {"id": 24,  "name": "Fort Collins",                   "address": "3030 S College Ave Ste 100, Fort Collins"},
    {"id": 25,  "name": "Fort Morgan",                    "address": "231 Prospect St, Ft Morgan"},
    {"id": 34,  "name": "Frisco",                         "address": "37 County Rd 1005, Frisco"},
    {"id": 35,  "name": "Glenwood Springs",               "address": "51027 Hwy 6 and 24, Glenwood Springs"},
    {"id": 13,  "name": "Golden",                         "address": "16950 W Colfax Ave Ste 104, Golden"},
    {"id": 36,  "name": "Grand Junction",                 "address": "222 S 6th Ste 111, Grand Junction"},
    {"id": 27,  "name": "Greeley",                        "address": "2320 Reservoir Rd Ste A, Greeley"},
    {"id": 39,  "name": "Gunnison",                       "address": "302 N Main St, Gunnison"},
    {"id": 17,  "name": "La Junta",                       "address": "13 W 3rd St Ste 101, La Junta"},
    {"id": 18,  "name": "Lamar",                          "address": "3505 S Main St, Lamar"},
    {"id": 92,  "name": "Longmont (new, opens 4/29/26)",  "address": "2144 Main St, Longmont"},
    {"id": 28,  "name": "Longmont (old, closes 4/23/26)", "address": "917 S Main St Ste 600, Longmont"},
    {"id": 29,  "name": "Loveland",                       "address": "118 E 29th St Ste F, Loveland"},
    {"id": 51,  "name": "Meeker",                         "address": "555 Main St, Meeker"},
    {"id": 37,  "name": "Montrose",                       "address": "2305 S Townsend Ave Unit C, Montrose"},
    {"id": 20,  "name": "Parker",                         "address": "17924 Cottonwood Dr, Parker"},
    {"id": 21,  "name": "Pueblo",                         "address": "827 W 4th St, Pueblo"},
    {"id": 47,  "name": "Salida",                         "address": "448 E 1st St, Salida"},
    {"id": 38,  "name": "Steamboat Springs",               "address": "425 Anglers Dr Ste C, Steamboat Springs"},
    {"id": 26,  "name": "Sterling",                       "address": "714 W Main St, Sterling"},
    {"id": 22,  "name": "Trinidad",                       "address": "200 E First St Rm 100, Trinidad"},
    {"id": 86,  "name": "Westgate",                       "address": "3265 S Wadsworth Blvd #3A, Lakewood"},
    {"id": 44,  "name": "Westminster",                    "address": "8464 Federal Blvd, Westminster"},
]

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "origin": "https://coloradoappt.cxmflow.com",
    "referer": BASE_URL,
    "upgrade-insecure-requests": "1",
}

VALID_TYPES = [
    "CDL Written Test",
    "First Time CO DL/ID/Permit",
    "Renew Colorado Driver License/ID/Permit",
    "Written Test",
]

# ── HTML Parsers ──────────────────────────────────────────────────────────────

def extract(html: str, name: str) -> Optional[str]:
    patterns = [
        rf'name="{re.escape(name)}"\s+value="([^"]*)"',
        rf'value="([^"]*)"\s+name="{re.escape(name)}"',
        rf'name="{re.escape(name)}"\s+[^>]*value="([^"]*)"',
        rf'value="([^"]*)"\s+[^>]*name="{re.escape(name)}"',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_csrf(html: str) -> Optional[str]:
    matches = re.findall(
        r'name="__RequestVerificationToken"\s+[^>]*value="([^"]*)"',
        html, re.IGNORECASE
    )
    if not matches:
        matches = re.findall(
            r'value="([^"]*)"\s+[^>]*name="__RequestVerificationToken"',
            html, re.IGNORECASE
        )
    return matches[-1] if matches else None


def extract_step_controls(html: str, field_name: str) -> dict:
    idx = html.find(f'value="{field_name}"')
    if idx == -1:
        idx = html.find(field_name)
    if idx == -1:
        return {}
    start   = max(0, idx - 3000)
    end     = min(len(html), idx + 3000)
    snippet = html[start:end]

    def grab(name):
        return extract(snippet, name)

    return {
        "step_control_id": grab("StepControls[0].StepControlId"),
        "step_step_id":    grab("StepControls[0].Step.StepId"),
        "model_type_name": grab("StepControls[0].Model.ModelTypeName"),
        "model_id":        grab("StepControls[0].Model.ModelId"),
        "target_type":     grab("StepControls[0].TargetTypeName"),
    }


def parse_appointment_types(html: str) -> list:
    types = []
    pattern = re.compile(
        r'<div[^>]+class="[^"]*QflowObjectItem[^"]*DataControlBtn[^"]*"[^>]+data-id="(\d+)"[^>]*>\s*<p>([^<]+)</p>',
        re.IGNORECASE | re.DOTALL
    )
    for m in pattern.finditer(html):
        types.append({"id": m.group(1), "name": m.group(2).strip()})
    return types


def parse_available_dates(html: str) -> list[datetime]:
    candidates = []

    for m in re.finditer(r'data-datetime="(\d{1,2}/\d{1,2}/\d{4}[^"]+)"', html):
        val = m.group(1).strip()
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
            try:
                candidates.append(datetime.strptime(val, fmt))
                break
            except ValueError:
                continue

    for m in re.finditer(r'class="SingleDateTime"[^>]*>([^<]+)<', html):
        val = m.group(1).strip()
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
            try:
                candidates.append(datetime.strptime(val, fmt))
                break
            except ValueError:
                continue

    for m in re.finditer(r'data-date="(\d{4}-\d{2}-\d{2})"', html):
        surrounding = html[max(0, m.start()-100):m.end()+100]
        if 'disabled' not in surrounding.lower():
            try:
                candidates.append(datetime.strptime(m.group(1), "%Y-%m-%d"))
            except ValueError:
                pass

    if not candidates:
        return []

    today  = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    future = sorted(set(d for d in candidates if d >= today))
    return future if future else sorted(set(candidates))


# ── Sub-unit detection (offices like Westgate with an extra category page) ─────

# Keywords that identify the "Driver License" sub-unit when an office
# presents a category selection page instead of going straight to services.
_SUB_UNIT_PAGE_SIGNALS = (
    "driver license",
    "driver records", 
    "vehicle services",
    "vehicle service",
)

def is_sub_unit_page(html: str) -> bool:
    """Return True if the page is a sub-unit/category selector, not a service page."""
    items = parse_appointment_types(html)
    if not items:
        return False
    names_lower = [t["name"].lower() for t in items]
    return any(
        sig in name
        for name in names_lower
        for sig in _SUB_UNIT_PAGE_SIGNALS
    )

def pick_dl_sub_unit(html: str) -> Optional[dict]:
    """From a sub-unit page, pick the option that covers Driver License / Written Test."""
    items = parse_appointment_types(html)
    # Prefer exact keyword matches, ranked by priority
    for keyword in _SUB_UNIT_PAGE_SIGNALS:
        for item in items:
            if keyword in item["name"].lower():
                return item
    # Fallback: first item (usually the DL option)
    return items[0] if items else None


async def _post_unit(session, html: str, unit_id: str, debug: bool, label: str) -> str:
    """POST a sub-unit selection and return the resulting HTML."""
    csrf    = extract_csrf(html)
    journey = extract(html, "formJourney")
    step_id = extract(html, "StepId") or STEP_ID_LOCATION

    # Read the actual FieldName from the page instead of assuming "ParentUnitId"
    field_name = extract(html, "StepControls[0].FieldName") or "ParentUnitId"
    meta = extract_step_controls(html, field_name)

    body = {
        "__RequestVerificationToken":          csrf or "",
        "TargetTypeName":                      TARGET_TYPE,
        "StepId":                              step_id,
        "formJourney":                         journey or "",
        "StepControls[0].FieldName":           field_name,
        "StepControls[0].TargetTypeName":      meta.get("target_type") or CONTROL_TYPE,
        "StepControls[0].Model.ModelTypeName": meta.get("model_type_name") or MODEL_TYPE,
        "StepControls[0].Model.ModelId":       meta.get("model_id") or "",
        "StepControls[0].StepControlId":       meta.get("step_control_id") or "",
        "StepControls[0].Step.StepId":         meta.get("step_step_id") or step_id,
        "StepControls[0].Model.Value":         unit_id,
        "StepControls[0].Model.Required":      "True",
        "StepControls[0].Model.ValidationDescription": "",
    }

    async with session.post(BASE_URL, data=body, headers={
        **HEADERS, "content-type": "application/x-www-form-urlencoded"
    }) as r:
        result_html = await r.text()

    if debug:
        print(f"  [{label}] sub-unit POST → field={field_name}, status={r.status}, len={len(result_html)}")

    return result_html


# ── Core: check one office ────────────────────────────────────────────────────

async def check_office(office: dict, appt_type_name: str, debug: bool = False) -> dict:
    result = {**office, "earliest_date": None, "available_dates": [], "matched_type": None, "error": None}

    connector = aiohttp.TCPConnector(ssl=False)
    timeout   = aiohttp.ClientTimeout(total=45)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        try:
            async with session.get(BASE_URL, headers=HEADERS) as r:
                initial_html = await r.text()

            csrf1    = extract_csrf(initial_html)
            journey1 = extract(initial_html, "formJourney")
            meta1    = extract_step_controls(initial_html, "ParentUnitId")

            if debug:
                print(f"[{office['name']}] Step1 status: {r.status}, csrf={'yes' if csrf1 else 'NO'}")

            if not csrf1:
                result["error"] = "Could not parse initial page (no CSRF token)"
                return result

            body1 = {
                "__RequestVerificationToken":          csrf1,
                "TargetTypeName":                      TARGET_TYPE,
                "StepId":                              STEP_ID_LOCATION,
                "formJourney":                         journey1 or "",
                "StepControls[0].FieldName":           "ParentUnitId",
                "StepControls[0].TargetTypeName":      meta1.get("target_type") or CONTROL_TYPE,
                "StepControls[0].Model.ModelTypeName": meta1.get("model_type_name") or MODEL_TYPE,
                "StepControls[0].Model.ModelId":       meta1.get("model_id") or "",
                "StepControls[0].StepControlId":       meta1.get("step_control_id") or "",
                "StepControls[0].Step.StepId":         meta1.get("step_step_id") or STEP_ID_LOCATION,
                "StepControls[0].Model.Value":         str(office["id"]),
                "StepControls[0].Model.Required":      "True",
                "StepControls[0].Model.ValidationDescription": "",
            }

            async with session.post(BASE_URL, data=body1, headers={
                **HEADERS, "content-type": "application/x-www-form-urlencoded"
            }) as r:
                service_html = await r.text()

            # ── Extra step: sub-unit category page (e.g. Westgate) ────────────
            if office["id"] == 86 and is_sub_unit_page(service_html):
                sub_unit = pick_dl_sub_unit(service_html)
                if not sub_unit:
                    result["error"] = "Sub-unit page found but could not identify Driver License option"
                    return result
                if debug:
                    print(f"[{office['name']}] Sub-unit page detected → selecting '{sub_unit['name']}' (id={sub_unit['id']})")
                service_html = await _post_unit(session, service_html, sub_unit["id"], debug, office["name"])

            appt_types = parse_appointment_types(service_html)
            if not appt_types:
                result["error"] = "No appointment types found on service page"
                return result

            search  = appt_type_name.lower().strip()
            matched = None
            for t in appt_types:
                if t["name"].lower() == search:
                    matched = t; break
            if not matched:
                for t in appt_types:
                    if t["name"].lower().startswith(search):
                        matched = t; break
            if not matched:
                candidates = [t for t in appt_types if search in t["name"].lower()]
                if candidates:
                    matched = min(candidates, key=lambda t: len(t["name"]))

            if not matched:
                available = ", ".join(t["name"] for t in appt_types)
                result["error"] = f'Type "{appt_type_name}" not found. Available: {available}'
                return result

            result["matched_type"] = matched["name"]

            csrf2    = extract_csrf(service_html)
            journey2 = extract(service_html, "formJourney")
            meta2    = extract_step_controls(service_html, "ServiceId")

            body2 = {
                "__RequestVerificationToken":          csrf2 or "",
                "TargetTypeName":                      TARGET_TYPE,
                "StepId":                              STEP_ID_SERVICE,
                "formJourney":                         journey2 or "",
                "StepControls[0].FieldName":           "ServiceId",
                "StepControls[0].TargetTypeName":      meta2.get("target_type") or CONTROL_TYPE,
                "StepControls[0].Model.ModelTypeName": meta2.get("model_type_name") or MODEL_TYPE,
                "StepControls[0].Model.ModelId":       meta2.get("model_id") or "",
                "StepControls[0].StepControlId":       meta2.get("step_control_id") or "",
                "StepControls[0].Step.StepId":         meta2.get("step_step_id") or STEP_ID_SERVICE,
                "StepControls[0].Model.Value":         matched["id"],
                "StepControls[0].Model.Required":      "True",
                "StepControls[0].Model.ValidationDescription": "",
            }

            async with session.post(BASE_URL, data=body2, headers={
                **HEADERS, "content-type": "application/x-www-form-urlencoded"
            }) as r:
                calendar_html = await r.text()

            if debug:
                hits = re.findall(r'data-datetime="([^"]+)"', calendar_html)
                print(f"[{office['name']}] data-datetime hits: {hits[:5]}")

            available = parse_available_dates(calendar_html)
            result["available_dates"] = available
            result["earliest_date"] = available[0] if available else None
            if not available:
                result["error"] = "No available dates found (office may be fully booked)"

        except Exception as e:
            result["error"] = str(e)

    return result


# ── Public API (used by api.py) ───────────────────────────────────────────────

async def search_offices(appt_type: str, office_filter: Optional[str] = None, debug: bool = False) -> list[dict]:
    """
    Search all (or one) offices for the given appointment type.
    Returns a list of result dicts, each with keys:
      id, name, address, earliest_date (datetime|None), matched_type, error
    """
    offices = OFFICES
    if office_filter:
        offices = [o for o in OFFICES if office_filter.lower() in o["name"].lower()]

    BATCH = 6
    all_results = []

    for i in range(0, len(offices), BATCH):
        batch        = offices[i:i + BATCH]
        tasks        = [check_office(o, appt_type, debug=debug) for o in batch]
        batch_results = await asyncio.gather(*tasks)
        all_results.extend(batch_results)

    return all_results


# ── CLI (unchanged behaviour) ─────────────────────────────────────────────────

def print_results(results: list, appt_type: str):
    found   = [r for r in results if r["earliest_date"]]
    no_date = [r for r in results if not r["earliest_date"]]
    found.sort(key=lambda r: r["earliest_date"])

    print(f"\n{'='*70}")
    print(f"  Colorado DMV — {appt_type}")
    print(f"  Searched {len(results)} offices  |  {len(found)} have availability")
    print(f"{'='*70}\n")

    if found:
        print(f"  {'#':<4} {'Office':<32} {'Earliest':<22} {'Days Away'}")
        print(f"  {'-'*4} {'-'*32} {'-'*22} {'-'*10}")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for i, r in enumerate(found, 1):
            days     = (r["earliest_date"] - today).days
            date_str = r["earliest_date"].strftime("%a %b %d, %I:%M %p")
            days_str = f"{days}d" if days > 0 else "Today!"
            print(f"  {i:<4} {r['name']:<32} {date_str:<22} {days_str}")

    if no_date:
        print(f"\n  ── No availability / errors ({len(no_date)} offices) ──")
        for r in no_date:
            print(f"  • {r['name']:<30}  {r.get('error') or 'No dates found'}")

    print(f"\n{'='*70}\n")


async def _cli_main(appt_type: str, debug: bool, single: Optional[str]):
    filter_ = single
    if single:
        offices = [o for o in OFFICES if single.lower() in o["name"].lower()]
        if not offices:
            print(f"No office matching '{single}'")
            return
        print(f"\n DEBUG mode - checking only: {offices[0]['name']}\n")
    else:
        print(f"\n Searching for '{appt_type}' across {len(OFFICES)} Colorado DMV offices...")
        print("   (This may take 30-60 seconds)\n")

    results = await search_offices(appt_type, office_filter=filter_, debug=debug)
    print_results(results, appt_type)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage:")
        print('  python dmv.py "Written Test"')
        print('  python dmv.py "Written Test" --debug')
        print('  python dmv.py "Written Test" --office Adams --debug')
        print("\nAvailable appointment types:")
        for t in VALID_TYPES:
            print(f"  - {t}")
        print()
        sys.exit(1)

    appt_type = sys.argv[1]
    debug     = "--debug" in sys.argv
    single    = None
    if "--office" in sys.argv:
        idx = sys.argv.index("--office")
        if idx + 1 < len(sys.argv):
            single = sys.argv[idx + 1]

    asyncio.run(_cli_main(appt_type, debug=debug, single=single))