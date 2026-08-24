"""Real end-to-end test over HTTP against a running server (not chained Python calls).

Usage:
    .venv/bin/python scripts/seed_test_patient.py   # once, prints access_token/patient_id
    .venv/bin/uvicorn app.main:app &
    .venv/bin/python scripts/test_e2e_http.py <access_token> <patient_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
PHOTOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "test_photos"

MEDICATIONS = [
    ("血脂康胶囊", ["6014.JPG", "6015.JPG"]),
    ("琥珀酸美托洛尔缓释片", ["6019.JPG", "6020.JPG"]),
    ("阿普唑仑片", ["6023.JPG", "6024.JPG"]),
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    token, patient_id = argv

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        print("=== POST /api/session ===")
        r = client.post("/api/session", params={"t": token})
        r.raise_for_status()
        print(r.json())
        assert r.json()["patient_id"] == patient_id

        for label, filenames in MEDICATIONS:
            print(f"\n=== {label}: POST /api/assets x{len(filenames)} ===")
            asset_ids = []
            for fname in filenames:
                path = PHOTOS_DIR / fname
                with path.open("rb") as f:
                    r = client.post(
                        "/api/assets",
                        params={"t": token},
                        data={"kind": "medbox"},
                        files={"file": (fname, f, "image/jpeg")},
                    )
                r.raise_for_status()
                asset_id = r.json()["asset_id"]
                asset_ids.append(asset_id)
                print(f"  {fname} -> asset {asset_id}")

            print(f"=== {label}: POST /api/parse/medbox ===")
            r = client.post("/api/parse/medbox", params={"t": token}, json={"asset_ids": asset_ids})
            r.raise_for_status()
            draft = r.json()
            new_item = draft["items"][-1]
            print(f"  parsed: {new_item}")
            print(f"  alerts: {draft['alerts']}  blocked: {draft['blocked']}")

            print(f"=== {label}: POST /api/regimen/confirm ===")
            r = client.post(
                "/api/regimen/confirm",
                params={"t": token},
                json={"medication_id": new_item["medication_id"], "fields": {}, "confirmed": True},
            )
            r.raise_for_status()
            print(f"  {r.json()}")

        print("\n=== POST /api/device/register ===")
        r = client.post("/api/device/register", json={"patient_id": patient_id})
        r.raise_for_status()
        device_token = r.json()["device_token"]
        print(f"  device_token={device_token}")

        print("\n=== GET /api/schedule (as the Android device would) ===")
        r = client.get(
            "/api/schedule",
            params={"since": "2020-01-01T00:00:00"},
            headers={"X-Device-Token": device_token},
        )
        r.raise_for_status()
        schedule = r.json()
        print(f"  {len(schedule['items'])} dose(s) scheduled:")
        for item in schedule["items"]:
            print(f"    {item['scheduled_at']}  {item['generic_name']}  photo={item['photo_url']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
