import os, sys, re, ssl, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, ".wheels")
os.makedirs(OUT, exist_ok=True)

PKG = sys.argv[1] if len(sys.argv) > 1 else "cadquery-ocp"
TAG = sys.argv[2] if len(sys.argv) > 2 else "cp312-cp312-win_amd64"
INDEX = f"https://pypi.tuna.tsinghua.edu.cn/simple/{PKG}/"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(INDEX, headers={"User-Agent": "pip/26"})
html = urllib.request.urlopen(req, context=ctx, timeout=60).read().decode("utf-8", "ignore")
print("index bytes:", len(html))

parts = html.split('href="')
links = [p.split('"')[0] for p in parts[1:]]
links = [l for l in links if l.endswith(".whl") or ".whl#" in l]
print("whl links:", len(links))

cands = [l for l in links if TAG in l]
print("matching", TAG, ":", len(cands))
if not cands:
    print("sample:", links[:3])
    sys.exit(1)

# pick highest version: sort by version-ish token
def ver_key(l):
    m = re.search(r"_ocp-([0-9][^-]*)-", l) or re.search(r"-([0-9][^-]*)-" + re.escape(TAG), l)
    return m.group(1) if m else "0"

cands.sort(key=lambda l: [int(x) if x.isdigit() else x for x in re.split(r"[.]", ver_key(l))] if all(x.isdigit() for x in ver_key(l).split(".")) else [0])
url = cands[-1]
if url.startswith("../"):
    url = "https://pypi.tuna.tsinghua.edu.cn/simple/" + PKG + "/" + url
fn = url.split("#")[0].split("/")[-1]
dest = os.path.join(OUT, fn)
print("chosen:", fn)

req = urllib.request.Request(url, headers={"User-Agent": "pip/26"})
with urllib.request.urlopen(req, context=ctx, timeout=180) as r, open(dest, "wb") as f:
    total = 0
    last = 0
    while True:
        chunk = r.read(1 << 20)
        if not chunk:
            break
        f.write(chunk)
        total += len(chunk)
        if total - last >= 25 << 20:
            last = total
            print(f"  {total/1048576:.0f} MB", flush=True)
print("saved", dest, os.path.getsize(dest))
