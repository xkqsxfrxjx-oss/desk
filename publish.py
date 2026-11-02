"""Plan B publisher: web/ + encrypted data dir -> gh-pages as ONE fresh orphan commit (force push, no history)."""
import base64, os, shutil, subprocess, tempfile
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/xkqsxfrxjx-oss/desk.git"
STAGE = os.path.join(ROOT, "publish")          # api.py writes encrypted files to publish/d/{DATA_PATH}/

class PublishError(Exception): pass

def publish():
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok: raise PublishError("GITHUB_TOKEN missing")
    out = tempfile.mkdtemp(prefix="pub-")
    try:
        shutil.copytree(os.path.join(ROOT, "web"), out, dirs_exist_ok=True)
        if os.path.isdir(os.path.join(STAGE, "d")):
            shutil.copytree(os.path.join(STAGE, "d"), os.path.join(out, "d"), dirs_exist_ok=True)
        g = lambda *a: subprocess.run(["git", *a], cwd=out, check=True, capture_output=True)
        g("init", "-q", "-b", "gh-pages"); g("add", "-A")
        g("-c", "user.name=xkqsxfrxjx-oss", "-c", "user.email=xkqsxfrxjx-oss@users.noreply.github.com", "commit", "-qm", "publish")
        hdr = "Authorization: Basic " + base64.b64encode(f"x-access-token:{tok}".encode()).decode()
        env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader", GIT_CONFIG_VALUE_0=hdr)
        r = subprocess.run(["git", "push", "-q", "-f", REPO, "gh-pages:gh-pages"], cwd=out, env=env, capture_output=True, text=True, timeout=120)
        if r.returncode: raise PublishError("push failed: " + r.stderr.replace(tok, "***")[-300:])
    finally:
        shutil.rmtree(out, ignore_errors=True)

if __name__ == "__main__":
    publish(); print("published")
