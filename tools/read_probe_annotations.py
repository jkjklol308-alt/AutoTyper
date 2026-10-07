"""Read the AUTOTYPER-* workflow annotations and decode the probe payload."""

import base64
import json
import subprocess
import sys
import zlib
from pathlib import Path

REPO = "jkjklol308-alt/AutoTyper"


def api(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def check_runs(sha):
    data = api(f"/repos/{REPO}/commits/{sha}/check-runs")
    return data["check_runs"]


def annotations(check_run_id):
    data = api(f"/repos/{REPO}/check-runs/{check_run_id}/annotations")
    return data if isinstance(data, list) else data.get("annotations", [])


def decode(messages):
    """Reassemble chunked AUTOTYPER-PROBE payloads from annotation messages."""
    chunks = {}
    for message in messages:
        if "AUTOTYPER-PROBE:" not in message:
            continue
        tail = message.split("AUTOTYPER-PROBE:", 1)[1].strip()
        name, _, rest = tail.partition(":")
        index, _, body = rest.partition(":")
        position, _, total = index.partition("/")
        chunks.setdefault((name, int(total)), {})[int(position)] = body
    payloads = {}
    for (name, total), parts in chunks.items():
        if len(parts) != total:
            print(f"warning: {name}: incomplete payload ({len(parts)}/{total} chunks)")
            continue
        blob = "".join(parts[i] for i in range(1, total + 1))
        try:
            payloads[name] = json.loads(zlib.decompress(base64.b64decode(blob)).decode())
        except Exception as err:
            print(f"warning: {name}: could not decode ({err})")
    return payloads


def main(sha, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for run in check_runs(sha):
        notes = annotations(run["id"])
        if not notes:
            continue
        print(f"=== {run['name']} ({run['conclusion']}) ===")
        for note in notes:
            message = note.get("message", "")
            if "AUTOTYPER-PROBE:" not in message:
                print(" -", message[:300])
        decoded = decode([n.get("message", "") for n in notes])
        for name, payload in decoded.items():
            if name == "images":
                run_name = run["name"].replace(" ", "_").replace("(", "").replace(")", "")
                for key, blob in payload.items():
                    if key == "error":
                        print("image error:", blob)
                        continue
                    (out / f"{run_name}.{key}.png").write_bytes(base64.b64decode(blob))
                    print(f"wrote {out / f'{run_name}.{key}.png'}")
                continue
            report = payload.get("report", {})
            print("report:", json.dumps(report.get("field_mismatches"), indent=2))
            print("shade:", report.get("shade"), "tk:", report.get("tk"),
                  "tcl:", report.get("tcl"), "screenshot:", report.get("screenshot"))
            print("field_actual:", json.dumps(report.get("field_actual"), indent=2))
            print("strip:", json.dumps(report.get("shade_strip_actual")))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "probe-art")
