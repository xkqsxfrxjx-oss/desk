import os, re, subprocess
import links
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def test_coin_url_has_ref():
    u = links.coin_url("F6XkiTNf8irwMRSujYmzQhr3FKi2MK88i1uUdCNPpump", "solana")
    assert u == "https://fomo.family/coin?address=F6XkiTNf8irwMRSujYmzQhr3FKi2MK88i1uUdCNPpump&chainId=1399811149&r=savipww&source=share_link"
    assert links.coin_url("0xabc", "base").endswith("chainId=8453&r=savipww&source=share_link")
    assert "chainId=56&" in links.coin_url("0xabc", "bnb") and "chainId=4663&" in links.coin_url("0xabc", "robinhood")
def test_unknown_chain_is_signup():
    assert links.coin_url("abc", "dogechain") == links.SIGNUP_URL == "https://fomo.family/r/savipww"
    assert links.coin_url("abc", "Solana") == links.SIGNUP_URL
def test_profile():
    assert links.profile_url("@rangeri") == links.profile_url("rangeri") == "https://fomo.family/profile/rangeri?source=share_link&r=savipww"
def test_repo_grep():
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    bad = []
    for f in files:
        if f.startswith("tests/") or not os.path.isfile(os.path.join(ROOT, f)): continue
        txt = open(os.path.join(ROOT, f), errors="ignore").read()
        for u in re.findall(r"https?://[^\s\"'<>)]*fomo[^\s\"'<>)]*", txt):
            if "{" in u: continue   # f-string templates inside links.py
            if "savipww" not in u: bad.append((f, u))
        for s in re.findall(r"https?://(?:bit\.ly|t\.co|tinyurl\.com|fomo\.link)/\S+", txt): bad.append((f, s))
    assert not bad, bad
    # only links.py builds fomo URLs
    builders = [f for f in files if f.endswith(".py") and not f.startswith("tests/") and f != "links.py"
                and "fomo.family" in open(os.path.join(ROOT, f)).read()]
    assert builders == [], builders
def test_rendered_pushes_carry_ref(c):
    import asyncio, notifier
    from tests.test_risk import open_pos
    from agents.risk import Risk
    open_pos(c, 1.0); asyncio.run(Risk(c).evaluate(dict(c.execute("select p.*,'x' name from positions p").fetchone()), 0.5, 1000))
    for p in notifier.SENT:
        for _, u in p["buttons"]:
            if u.startswith("http"): assert "r=savipww" in u
