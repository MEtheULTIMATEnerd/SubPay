"""Create the "Riverside Commercial Fitout" demo project through the API.

Everything goes through the same endpoints the web app uses, so the demo data
obeys the same rules as real data: the contract and evidence files are really
stored, the claim schedule really comes from extraction, and every record
belongs to the signed-in user's organisation.

    cd services/api
    python -m scripts.seed_demo --email ollie@kearneyformwork.test

The API must be running (see README.md) and the account must already exist.
The password is asked for when the script runs, or read from SEED_PASSWORD. It
is never stored. All names, numbers and files are fictional and generated here.

Safe to run again: if the organisation already has a project with this name,
nothing is changed.
"""

import argparse
import getpass
import json
import os
import struct
import sys
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx2

from app.core.config import get_settings

PROJECT = {
    "name": "Riverside Commercial Fitout",
    "client_name": "Northbank Builders",
    "site_address": "42 Riverside Quay, Southbank VIC",
}
CONTRACT_FILENAME = "Riverside_Commercial_Fitout_Electrical_Subcontract.pdf"

# The mock extraction returns this schedule for a "fitout" contract (app/ai/extraction.py).
SCHEDULE_LINES = [
    "Riverside Commercial Fitout - Electrical Subcontract (fictional demo document)",
    "Head contractor: Northbank Builders     Subcontractor: demo organisation",
    "",
    "Schedule of rates",
    "4.2  Electrical conduit installation   120 m     @ $45.00      $5,400.00",
    "4.3  Cable tray installation            80 m     @ $60.00      $4,800.00",
    "4.5  Switchboard installation            1 item  @ $12,500.00  $12,500.00",
    "     Notify builder 5 days before energisation.",
    "6.1  Lighting fit-off                                           $7,600.00",
    "",
    "Progress claims are due on the 25th of each month.",
]


# ---- sample files, generated so no binary files live in the repository ------------


def make_pdf(lines: list[str]) -> bytes:
    """A small, valid one-page PDF showing the given lines of text."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text = "BT /F1 11 Tf 50 780 Td 16 TL " + " ".join(f"({escape(line)}) Tj T*" for line in lines)
    stream = text.encode("latin-1", "replace") + b" ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def make_png(base: tuple[int, int, int], accent: tuple[int, int, int]) -> bytes:
    """A 480x320 placeholder picture: a colour field with diagonal bands.
    Clearly not a real site photo, but a real image the library can preview."""
    width, height, band = 480, 320, 48
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # no filter
        for x in range(width):
            shade = 1 - 0.35 * y / height
            colour = accent if ((x + y) // band) % 4 == 0 else base
            rows += bytes(int(channel * shade) for channel in colour)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


# ---- the demo evidence --------------------------------------------------------------


@dataclass
class DemoEvidence:
    title: str
    description: str
    evidence_type: str
    days_ago: int
    location: str | None
    source: str = "mobile_upload"
    file: tuple[str, bytes, str] | None = None
    tags: list[str] = field(default_factory=list)
    archived: bool = False


def demo_evidence() -> list[DemoEvidence]:
    timesheet = (
        b"date,worker,task,hours\n"
        b"Mon,J. Tran,Conduit install Level 2 east,8\n"
        b"Mon,M. Silva,Conduit install Level 2 east,8\n"
        b"Tue,J. Tran,Cable tray Level 2 grid B3-B6,7.5\n"
        b"Wed,M. Silva,Switchboard MSB-2 positioning,6\n"
    )
    docket = make_pdf(
        [
            "DELIVERY DOCKET 88213 (fictional demo document)",
            "Supplier: Yarra Electrical Wholesale",
            "Deliver to: Riverside Commercial Fitout, 42 Riverside Quay",
            "",
            "25 mm rigid conduit, 4 m lengths     x 32",
            "25 mm saddles                        x 150",
            "Cable tray 300 mm, 3 m lengths       x 28",
            "",
            "Received in good order on site.",
        ]
    )
    instruction = make_pdf(
        [
            "SITE INSTRUCTION SI-014 (fictional demo document)",
            "From: Northbank Builders, site manager",
            "To: electrical subcontractor",
            "",
            "Install six additional double power outlets in tenancy 3, Level 2,",
            "at the positions marked on drawing E-203 revision C.",
            "",
            "This work is not included in the subcontract schedule of rates.",
        ]
    )
    # The first four match the team's agreed example:
    # EV-001 and EV-002 site photos, EV-003 a docket, EV-004 a site instruction.
    return [
        DemoEvidence(
            title="Conduit run, Level 2 east corridor",
            description=(
                "Electrical conduit installed along the Level 2 east corridor, about 60 m, "
                "saddles fixed at 1 m centres."
            ),
            evidence_type="photo",
            days_ago=12,
            location="Level 2, east corridor",
            file=("IMG_2041.png", make_png((70, 110, 150), (240, 200, 60)), "image/png"),
            tags=["conduit", "level 2"],
        ),
        DemoEvidence(
            title="Conduit run, Level 2 west corridor",
            description="Remaining conduit installed along the west corridor, about 60 m.",
            evidence_type="photo",
            days_ago=9,
            location="Level 2, west corridor",
            file=("IMG_2063.png", make_png((60, 120, 110), (240, 200, 60)), "image/png"),
            tags=["conduit", "level 2"],
        ),
        DemoEvidence(
            title="Delivery docket 88213, conduit and cable tray",
            description="Supplier docket for conduit, saddles and cable tray, signed on delivery.",
            evidence_type="docket",
            days_ago=14,
            location="Site gate",
            source="desktop_upload",
            file=("Docket_88213.pdf", docket, "application/pdf"),
            tags=["delivery"],
        ),
        DemoEvidence(
            title="Site instruction SI-014, extra power outlets in tenancy 3",
            description=(
                "Builder's written instruction for six extra double power outlets in tenancy 3. "
                "Not in the subcontract schedule."
            ),
            evidence_type="document",
            days_ago=3,
            location="Level 2, tenancy 3",
            source="desktop_upload",
            file=("Site_instruction_SI-014.pdf", instruction, "application/pdf"),
            tags=["site instruction"],
        ),
        DemoEvidence(
            title="Cable tray above ceiling grid",
            description="Cable tray installed above the ceiling grid, grid lines B3 to B6.",
            evidence_type="photo",
            days_ago=8,
            location="Level 2, grid B3 to B6",
            file=("IMG_2077.png", make_png((95, 95, 105), (200, 80, 60)), "image/png"),
            tags=["cable tray", "level 2"],
        ),
        DemoEvidence(
            title="Switchboard MSB-2 delivered and positioned",
            description=(
                "Main switchboard MSB-2 delivered and set in position in the plant room. "
                "Not yet terminated or energised."
            ),
            evidence_type="photo",
            days_ago=5,
            location="Level 1 plant room",
            file=("IMG_2102.png", make_png((120, 90, 70), (230, 230, 230)), "image/png"),
            tags=["switchboard"],
        ),
        DemoEvidence(
            title="Timesheet, electrical crew",
            description="Crew hours for conduit, cable tray and switchboard positioning.",
            evidence_type="document",
            days_ago=6,
            location=None,
            source="desktop_upload",
            file=("Timesheet_electrical_crew.csv", timesheet, "text/csv"),
            tags=["labour"],
        ),
        DemoEvidence(
            title="Phone call with site supervisor",
            description=(
                "Site supervisor confirmed by phone that the Level 2 conduit rough-in "
                "passed inspection."
            ),
            evidence_type="message",
            days_ago=4,
            location=None,
            source="desktop_upload",
        ),
        DemoEvidence(
            title="Conduit run, Level 2 east corridor (blurred)",
            description="Blurred duplicate of the east corridor photo. Archived, not deleted.",
            evidence_type="photo",
            days_ago=12,
            location="Level 2, east corridor",
            file=("IMG_2040.png", make_png((70, 110, 150), (150, 150, 150)), "image/png"),
            archived=True,
        ),
    ]


# ---- seeding --------------------------------------------------------------------------


class SeedError(Exception):
    """Something the person running the script can act on."""


def _checked(response: Any, what: str) -> Any:
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:200]
        raise SeedError(f"Could not {what}: {response.status_code} {message}")
    return response.json()


def _wait(
    http: Any, url: str, headers: dict[str, str], sleep: Callable[[float], None]
) -> dict[str, Any]:
    """Poll a contract or evidence record until processing has finished."""
    record: dict[str, Any] = {}
    for _ in range(60):
        record = _checked(http.get(url, headers=headers), "check processing")
        if record["processing_status"] in ("ready", "failed"):
            break
        sleep(0.5)
    return record


def seed(
    http: Any,
    api: str,
    headers: dict[str, str],
    *,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, Any] | None:
    """Create the demo project. Returns a summary, or None when it already exists.

    `http` is an httpx2 client (the tests pass FastAPI's TestClient).
    """
    now = now or datetime.now(timezone.utc)

    offset = 0
    while True:  # active and archived projects alike
        page = _checked(
            http.get(f"{api}/projects", params={"limit": 200, "offset": offset}, headers=headers),
            "list projects",
        )["items"]
        if any(p["name"] == PROJECT["name"] for p in page):
            log(f'"{PROJECT["name"]}" already exists for this organisation. Nothing changed.')
            return None
        if len(page) < 200:
            break
        offset += 200

    project = _checked(
        http.post(
            f"{api}/projects",
            json={
                **PROJECT,
                "start_date": (now - timedelta(days=45)).date().isoformat(),
                "end_date": (now + timedelta(days=120)).date().isoformat(),
            },
            headers=headers,
        ),
        "create the project",
    )
    project_id = project["id"]
    log(f'Created project "{project["name"]}"')

    # ---- contract: upload, let extraction run, then review as a person would
    contract = _checked(
        http.post(
            f"{api}/projects/{project_id}/contracts",
            files={"file": (CONTRACT_FILENAME, make_pdf(SCHEDULE_LINES), "application/pdf")},
            headers=headers,
        ),
        "upload the contract",
    )
    contract = _wait(http, f"{api}/contracts/{contract['id']}", headers, sleep)
    items: list[dict[str, Any]] = []
    if contract["processing_status"] == "ready":
        items = _checked(
            http.get(f"{api}/contracts/{contract['id']}/items", headers=headers),
            "read the contract items",
        )["items"]
    else:
        log("Contract extraction did not finish (is the AI service down?). No items to review.")
    by_code = {item["item_code"]: item for item in items}
    log(f"Uploaded the contract: {len(items)} items extracted")

    reviewed = 0
    for code in ("4.2", "4.3"):
        if code in by_code:
            _checked(
                http.post(f"{api}/contract-items/{by_code[code]['id']}/confirm", headers=headers),
                f"confirm item {code}",
            )
            reviewed += 1
    if "4.5" in by_code:
        # A human correction: the AI's original stays in extracted_values.
        item_id = by_code["4.5"]["id"]
        _checked(
            http.patch(
                f"{api}/contract-items/{item_id}",
                json={"conditions": "Claimable 60% on delivery, 40% on energisation"},
                headers=headers,
            ),
            "edit item 4.5",
        )
        _checked(
            http.post(f"{api}/contract-items/{item_id}/confirm", headers=headers),
            "confirm item 4.5",
        )
        reviewed += 1
    # 6.1 is left as an AI draft: it has no quantity or rate and needs a human check.
    log(f"Reviewed {reviewed} items, left {len(items) - reviewed} as AI drafts")

    # ---- evidence
    created = []
    for entry in demo_evidence():
        captured_at = (now - timedelta(days=entry.days_ago)).replace(
            hour=1 + entry.days_ago % 6, minute=30, second=0, microsecond=0
        )
        metadata = {"location": entry.location, "source": entry.source, "tags": entry.tags}
        record = _checked(
            http.post(
                f"{api}/projects/{project_id}/evidence",
                files={"file": entry.file} if entry.file else None,
                data={
                    "title": entry.title,
                    "description": entry.description,
                    "evidence_type": entry.evidence_type,
                    "captured_at": captured_at.isoformat(),
                    "metadata": json.dumps(metadata),
                },
                headers=headers,
            ),
            f'add evidence "{entry.title}"',
        )
        _wait(http, f"{api}/evidence/{record['id']}", headers, sleep)
        if entry.archived:
            _checked(
                http.patch(
                    f"{api}/evidence/{record['id']}", json={"archived": True}, headers=headers
                ),
                f'archive "{entry.title}"',
            )
        created.append(record)
    archived = sum(1 for entry in demo_evidence() if entry.archived)
    log(f"Added {len(created)} evidence records ({archived} archived)")

    return {
        "project_id": project_id,
        "contract_id": contract["id"],
        "contract_items": len(items),
        "items_reviewed": reviewed,
        "evidence": [record["code"] for record in created],
    }


def sign_in(
    http: httpx2.Client, supabase_url: str, anon_key: str, email: str, password: str
) -> str:
    """Sign in through Supabase Auth and return the access token."""
    try:
        response = http.post(
            f"{supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers={"apikey": anon_key},
        )
    except httpx2.HTTPError as exc:
        raise SeedError(f"Could not reach Supabase at {supabase_url}: {exc}") from exc
    if response.status_code >= 400:
        raise SeedError(
            f"Could not sign in as {email}. Check the email and password, and that the "
            "account exists and its email is confirmed."
        )
    return response.json()["access_token"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="An existing SubPay account")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Where the API runs")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.supabase_base_url or not settings.supabase_anon_key:
        print("Set SUPABASE_URL and SUPABASE_ANON_KEY in services/api/.env first.", file=sys.stderr)
        return 1
    password = os.environ.get("SEED_PASSWORD") or getpass.getpass(f"Password for {args.email}: ")

    try:
        with httpx2.Client(timeout=120) as http:
            token = sign_in(
                http, settings.supabase_base_url, settings.supabase_anon_key, args.email, password
            )
            try:
                summary = seed(
                    http,
                    f"{args.api_url.rstrip('/')}{settings.api_v1_prefix}",
                    {"Authorization": f"Bearer {token}"},
                )
            except httpx2.HTTPError as exc:
                raise SeedError(
                    f"Could not reach the API at {args.api_url}. Is it running? ({exc})"
                ) from exc
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if summary:
        print("Done. Open the project in the web app to see it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
