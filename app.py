import re
import json
import threading
from flask import Flask, jsonify, render_template
import paramiko

app = Flask(__name__)

SERVERS = ["mcserver", "mcvmh1", "mcnas", "mcnas2", "workpc"]

SSH_KEY_PATH = "/home/storcli/.ssh/id_rsa"
STORCLI_CMD = "storcli64 /call show all"

SERVER_USER = {
    "mcserver": "plex",
    "mcvmh1":   "plex",
    "mcnas":    "plex",
    "mcnas2":   "plex",
    "workpc":   "admin",
}

SERVER_CMD = {
    "workpc": "sudo storcli64 /call show all",
}

# Cache
_cache = {}
_cache_lock = threading.Lock()


def run_storcli(hostname):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname,
            username=SERVER_USER.get(hostname, "plex"),
            key_filename=SSH_KEY_PATH,
            timeout=15,
        )
        cmd = SERVER_CMD.get(hostname, STORCLI_CMD)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        output = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return {"status": "ok", "raw": output, "error": err, "source": "storcli"}
    except Exception as e:
        return {"status": "error", "raw": "", "error": str(e), "source": "unknown"}
    finally:
        client.close()


def parse_lsblk_output(raw):
    """Parse lsblk --json output into the same drive dict format as storcli."""
    result = {"drives": [], "vdrives": [], "controller_info": {
        "Model": "HBA (IT mode)", "Controller Status": "N/A (no RAID)"
    }}
    try:
        data = json.loads(raw)
    except Exception:
        return result
    for dev in data.get("blockdevices", []):
        name = dev.get("name", "")
        if name.startswith("loop"):
            continue
        size  = dev.get("size") or "?"
        vendor = (dev.get("vendor") or "").strip()
        model  = (dev.get("model") or "").strip()
        serial = (dev.get("serial") or "").strip()
        tran   = (dev.get("tran") or "?").upper()
        rota   = str(dev.get("rota", "1"))
        med    = "HDD" if rota == "1" else "SSD"
        size_norm = size.replace("T", " TB").replace("G", " GB").replace("M", " MB")
        result["drives"].append({
            "id":     name,
            "State":  "Onln",
            "Size":   size_norm,
            "Intf":   tran,
            "Med":    med,
            "Model":  f"{vendor} {model}".strip(),
            "DG":     "—",
            "SeSz":   "—",
            "SED":    "—",
            "PI":     "—",
            "Sp":     "U",
            "Type":   "HBA",
            "Serial": serial,
        })
    return result


CTRL_FIELDS = [
    "Model", "Serial Number", "Controller Status", "Firmware Package Build",
    "Firmware Version", "Driver Version", "Current Controller Date/Time",
    "Operating system", "Memory", "ROC temperature", "Device Interface",
]


def _section_lines(raw, section_name):
    """Return the data lines from a storcli table section."""
    m = re.search(
        rf'{re.escape(section_name)}\s*:.*?\n=+\n\n-+\n.+?\n-+\n(.*?)\n-+',
        raw, re.DOTALL
    )
    if not m:
        return []
    return [l for l in m.group(1).splitlines() if l.strip()]


def _parse_drive_row(t):
    """Parse a tokenised PD table row into a drive dict. Returns None on failure."""
    # EID:Slt may be "19:0" (MegaRAID) or ":0" (IT-mode HBA, no enclosure)
    if not t or not re.match(r'\d*:\d+$', t[0]):
        return None
    d = {}
    try:
        d["EID:Slt"] = t[0];  d["id"] = t[0] if t[0] != ":0" else t[0]
        d["DID"]     = t[1]
        d["State"]   = t[2]
        d["DG"]      = t[3]
        d["Size"]    = t[4] + " " + t[5]
        d["Intf"]    = t[6]
        d["Med"]     = t[7]
        d["SED"]     = t[8]
        d["PI"]      = t[9]
        i = 10
        if t[i].endswith("B"):
            d["SeSz"] = t[i];  i += 1
        else:
            d["SeSz"] = t[i] + " " + t[i+1];  i += 2
        rest = t[i:]
        if len(rest) >= 3:
            d["Model"] = " ".join(rest[:-2])
            d["Sp"]    = rest[-2]
            d["Type"]  = rest[-1]
        elif len(rest) == 2:
            d["Model"] = rest[0];  d["Sp"] = rest[1]
        return d
    except IndexError:
        return None


def _parse_pd_list(raw):
    drives = []
    seen_ids = set()

    # Primary: summary PD LIST section (MegaRAID RAID controllers)
    for line in _section_lines(raw, "PD LIST"):
        d = _parse_drive_row(line.split())
        if d:
            drives.append(d)
            seen_ids.add(d["id"])

    # Always also scan individual drive mini-tables — needed for:
    #   - IT-mode HBAs (no PD LIST at all)
    #   - Multi-controller systems where extra controllers use mini-tables
    # Determine controller context for each block so :0 on /c1 vs /c2 get distinct IDs.
    for m in re.finditer(
        r'EID:Slt\s+DID\s+State.*?\n-+\n(.*?)\n-+',
        raw, re.DOTALL
    ):
        # Find the most recent "Controller = N" before this block
        ctrl_m = None
        for cm in re.finditer(r'^Controller = (\d+)\s*$', raw[:m.start()], re.MULTILINE):
            ctrl_m = cm
        ctrl_num = ctrl_m.group(1) if ctrl_m else "0"

        for line in m.group(1).splitlines():
            d = _parse_drive_row(line.split())
            if not d:
                continue
            # For no-enclosure slots like ":0", prefix with controller number
            if d["id"].startswith(":"):
                d["id"] = f"c{ctrl_num}{d['id']}"
                d["EID:Slt"] = d["id"]
            if d["id"] not in seen_ids:
                drives.append(d)
                seen_ids.add(d["id"])

    return drives


def _parse_vd_list(raw):
    vdrives = []
    for line in _section_lines(raw, "VD LIST"):
        t = line.split()
        if not t or not re.match(r'\d+/\d+', t[0]):
            continue
        d = {}
        try:
            d["DG/VD"]   = t[0];  d["id"] = t[0]
            d["TYPE"]    = t[1]
            d["State"]   = t[2]
            d["Access"]  = t[3]
            d["Consist"] = t[4]
            d["Cache"]   = t[5]
            d["Cac"]     = t[6]
            d["sCC"]     = t[7]
            d["Size"]    = t[8] + " " + t[9]
            d["Name"]    = " ".join(t[10:]) if len(t) > 10 else ""
            vdrives.append(d)
        except IndexError:
            pass
    return vdrives


def parse_storcli_output(raw):
    result = {"drives": [], "vdrives": [], "controller_info": {}}

    if not raw:
        return result

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Controller key=value info (only curated fields to avoid noise)
    for line in raw.splitlines():
        m = re.match(r'^([A-Za-z][A-Za-z0-9 /]+?)\s*=\s*(.+)$', line.strip())
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key in CTRL_FIELDS and val:
                result["controller_info"][key] = val

    result["drives"]  = _parse_pd_list(raw)
    result["vdrives"] = _parse_vd_list(raw)

    return result


def fetch_all():
    results = {}

    def fetch_one(host):
        data = run_storcli(host)
        parser = parse_lsblk_output if data.get("source") == "lsblk" else parse_storcli_output
        data["parsed"] = parser(data["raw"])
        with _cache_lock:
            results[host] = data

    threads = [threading.Thread(target=fetch_one, args=(h,)) for h in SERVERS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)

    return results


@app.route("/")
def index():
    return render_template("index.html", servers=SERVERS)


@app.route("/api/data")
def api_data():
    data = fetch_all()
    return jsonify(data)


@app.route("/api/data/<hostname>")
def api_data_host(hostname):
    if hostname not in SERVERS:
        return jsonify({"error": "unknown host"}), 404
    data = run_storcli(hostname)
    parser = parse_lsblk_output if data.get("source") == "lsblk" else parse_storcli_output
    data["parsed"] = parser(data["raw"])
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
