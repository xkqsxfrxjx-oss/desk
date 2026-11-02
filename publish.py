"""Publish web/ + encrypted data to gh-pages as ONE fresh orphan commit (force push, no history).
Usage: python publish.py  (data objects come from publish_data(); every JSON is encrypted)."""
import json, os, shutil, subprocess, sys, tempfile
from desk_crypto import encrypt, secrets_file
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/xkqsxfrxjx-oss/desk.git"
def publish(data: dict):
    s = secrets_file(); dp, tok = s["DATA_PATH"], s["APP_TOKEN"]
    out = tempfile.mkdtemp(prefix="pub-")
    try:
        shutil.copytree(os.path.join(ROOT, "web"), out, dirs_exist_ok=True)
        d = os.path.join(out, "d", dp); os.makedirs(d)
        for name, obj in data.items():
            json.dump(encrypt(obj, tok), open(os.path.join(d, name), "w"))
        g = lambda *a: subprocess.run(["git", *a], cwd=out, check=True, capture_output=True)
        g("init", "-q", "-b", "gh-pages"); g("add", "-A")
        g("-c", "user.name=xkqsxfrxjx-oss", "-c", "user.email=xkqsxfrxjx-oss@users.noreply.github.com", "commit", "-qm", "publish")
        tokv = os.environ["GITHUB_TOKEN"]
        import base64
        hdr = "Authorization: Basic " + base64.b64encode(f"x-access-token:{tokv}".encode()).decode()
        env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader", GIT_CONFIG_VALUE_0=hdr)
        r = subprocess.run(["git", "push", "-q", "-f", REPO, "gh-pages:gh-pages"], cwd=out, env=env, capture_output=True, text=True)
        if r.returncode: sys.exit("push failed: " + r.stderr.replace(tokv, "***")[-300:])
    finally:
        shutil.rmtree(out, ignore_errors=True)
if __name__ == "__main__":
    import datetime
    publish({"test.json": {"test": True, "ts": datetime.datetime.now(datetime.UTC).isoformat()}})
    print("published")
