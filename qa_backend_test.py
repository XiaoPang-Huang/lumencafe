# QA 独立验证 B：后端接口真调（通过容器内 httpx 走 :8000 真实 HTTP 链路）
import json
import sys
import httpx

BASE = "http://127.0.0.1:8000"
TOKEN = open("/tmp/qa_token.txt").read().strip()
H = {"Authorization": f"Bearer {TOKEN}"}

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))


# ---------- 0. 基线（先等限流窗口重置 + 清理上次残留） ----------
import time
time.sleep(65)  # skills-write 限流 20 次/分钟，等待上一轮窗口过期
import os
import subprocess
_r = httpx.get(BASE + "/skills/mine", headers=H)
for s in _r.json():
    httpx.delete(BASE + f"/skills/{s['id']}", headers=H)
for name in os.listdir("/app/skills"):
    if name != ".gitkeep":
        subprocess.run(["rm", "-rf", f"/app/skills/{name}"])

r = httpx.get(BASE + "/skills/mine", headers=H)
check("B0 GET /skills/mine 200", r.status_code == 200)
mine0 = r.json()
check("B0 基线 mine 为空（环境已清理）", mine0 == [], mine0)

# ---------- 1. upload 各分支 ----------
VALID_MD = """---
name: QA 上传 测试 Skill!
description: QA 端到端验证上传技能
version: 1.0
---

这是 QA 注入验证用的正文指令。当用户提到咖啡时，回复要带着咖啡师的热情。
"""


def upload(filename, content):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return httpx.post(
        BASE + "/skills/upload",
        headers=H,
        files={"file": (filename, content, "text/markdown")},
    )


r = upload("qa-upload.md", VALID_MD)
check("B1 合法上传 201", r.status_code == 201, r.status_code)
if r.status_code == 201:
    d = r.json()
    check("B1 回显 source=local-upload", d.get("source") == "local-upload", d.get("source"))
    check("B1 slug 清洗（QA 上传 测试 Skill! → qa-skill）",
          d.get("name") == "qa-skill", d.get("name"))
    check("B1 回显 path=skills/qa-skill/", d.get("path") == "skills/qa-skill/", d.get("path"))
    check("B1 enabled 默认开", d.get("enabled") is True)
    check("B1 无 prompt 回显", "prompt" not in d)
    upload_id = d.get("id")
else:
    upload_id = None
    print(r.text[:300])

r = upload("note.txt", VALID_MD)
check("B1 非 .md → 422", r.status_code == 422 and "md" in r.json().get("detail", ""), r.text[:120])

big = "---\nname: qa-big\ndescription: x\n---\n" + "正文" * 40000
r = upload("qa-big.md", big)
check("B1 >64KB → 422", r.status_code == 422 and "64KB" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-bad-utf8.md", b"\xff\xfe\x00\x01 not utf8 \xfa\xfb")
check("B1 坏 UTF-8 → 422", r.status_code == 422 and "UTF-8" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-nofm.md", "# 只有正文没有 frontmatter\n一些指令。")
check("B1 无 frontmatter → 422", r.status_code == 422 and "frontmatter" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-nodesc.md", "---\nname: qa-nodesc\n---\n有正文。")
check("B1 缺 description → 422", r.status_code == 422 and "description" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-noname.md", "---\ndescription: 只有描述\n---\n有正文。")
check("B1 缺 name → 422", r.status_code == 422 and "name" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-nobody.md", "---\nname: qa-nobody\ndescription: 有描述\n---\n   \n")
check("B1 无正文 → 422", r.status_code == 422 and "正文" in r.json().get("detail", ""), r.text[:120])

r = upload("qa-dup.md", VALID_MD)  # 同名（清洗后 slug 相同）→ 409
check("B1 重名 → 409", r.status_code == 409 and "同名" in r.json().get("detail", ""), r.text[:120])

# 失败请求不落盘
import subprocess
disk = subprocess.run(["ls", "-a", "/app/skills"], capture_output=True, text=True).stdout.split()
disk = [d for d in disk if d not in (".", "..")]
check("B1 校验失败不落盘（仅 .gitkeep + qa-skill）",
      sorted(disk) == sorted([".gitkeep", "qa-skill"]), disk)

# 落盘内容 source 键
md_on_disk = open("/app/skills/qa-skill/SKILL.md", encoding="utf-8").read()
check("B1 落盘 frontmatter source=local-upload", "source: local-upload" in md_on_disk)
check("B1 落盘保留用户原文其他键/正文", "QA 端到端验证上传技能" in md_on_disk and "咖啡师的热情" in md_on_disk)

# ---------- 2. mine / enabled ----------
r = httpx.get(BASE + "/skills/mine", headers=H)
mine = r.json()
up = [s for s in mine if s.get("source") == "local-upload"]
check("B2 mine 含本地上传条目", len(up) == 1, mine)
if up:
    check("B2 mine path 正确", up[0]["path"] == "skills/qa-skill/", up[0]["path"])
    check("B2 mine name=slug", up[0]["name"] == "qa-skill", up[0]["name"])
    check("B2 mine enabled 默认开", up[0]["enabled"] is True)

if upload_id:
    r = httpx.put(BASE + f"/skills/{upload_id}/enabled", headers=H, json={"enabled": False})
    check("B2 PUT enabled=false 200", r.status_code == 200, r.text[:120])
    r = httpx.get(BASE + "/skills/mine", headers=H)
    check("B2 开关后 mine enabled=false",
          [s for s in r.json() if s["id"] == upload_id][0]["enabled"] is False)
    r = httpx.put(BASE + "/skills/{0}/enabled".format(999999), headers=H, json={"enabled": False})
    check("B2 开关不存在 id → 404", r.status_code == 404, r.status_code)
    r = httpx.put(BASE + f"/skills/{upload_id}/enabled", headers=H, json={"enabled": True})
    check("B2 PUT enabled=true 200", r.status_code == 200)

# ---------- 3. catalog / install 保留 ----------
r = httpx.get(BASE + "/skills/catalog", headers=H)
check("B3 GET /skills/catalog 200", r.status_code == 200, r.status_code)
cat = r.json()
items = cat.get("items", [])
check("B3 catalog 返回 5 个 mock", len(items) == 5, len(items))
check("B3 catalog 含 installed 标记", all("installed" in i for i in items))

if items:
    sid = items[0]["skillhub_id"]
    r = httpx.post(BASE + "/skills/install", headers=H, json={"skillhub_id": sid})
    check("B3 POST /skills/install 201", r.status_code == 201, r.text[:200])
    install_id = r.json().get("id") if r.status_code == 201 else None
    if r.status_code == 201:
        d = r.json()
        check("B3 install 回显 source=skillhub", d.get("source") == "skillhub", d.get("source"))
        check("B3 install 回显 path", d.get("path", "").startswith("skills/"), d.get("path"))
        slug_dir = d.get("path", "").strip("/").split("/")[-1]
        import os
        check("B3 install 落盘", os.path.isdir(f"/app/skills/{slug_dir}"))
        disk2 = subprocess.run(["ls", "/app/skills"], capture_output=True, text=True).stdout.split()
        check("B3 混装落盘（skillhub+upload 两个目录）",
              "qa-skill" in disk2 and slug_dir in disk2, disk2)
    r2 = httpx.post(BASE + "/skills/install", headers=H, json={"skillhub_id": sid})
    check("B3 重复 install → 409", r2.status_code == 409, r2.status_code)
    r3 = httpx.post(BASE + "/skills/install", headers=H, json={"skillhub_id": "not-exist-id"})
    check("B3 不存在 id → 404", r3.status_code == 404, r3.status_code)

    # 混装 mine
    r = httpx.get(BASE + "/skills/mine", headers=H)
    mine = r.json()
    srcs = sorted([s["source"] for s in mine])
    check("B3 混装 mine 两来源", srcs == ["local-upload", "skillhub"], srcs)

    # ---------- 4. 卸载 ----------
    if install_id:
        r = httpx.delete(BASE + f"/skills/{install_id}", headers=H)
        check("B4 DELETE install 200", r.status_code == 200, r.status_code)
        import os
        check("B4 卸载后目录已删", not os.path.exists(f"/app/skills/{slug_dir}"))
        r = httpx.get(BASE + "/skills/mine", headers=H)
        check("B4 mine 不再含 skillhub 条目",
              all(s["source"] != "skillhub" for s in r.json()))

if upload_id:
    r = httpx.delete(BASE + f"/skills/{upload_id}", headers=H)
    check("B4 DELETE upload 200", r.status_code == 200, r.status_code)
    import os
    check("B4 卸载后上传目录已删", not os.path.exists("/app/skills/qa-skill"))
    r = httpx.get(BASE + "/skills/mine", headers=H)
    check("B4 mine 清空", r.json() == [], r.json())

r = httpx.delete(BASE + "/skills/999999", headers=H)
check("B4 卸载不存在 id → 404", r.status_code == 404, r.status_code)

# ---------- 5. 限流（写操作 20 次/分钟，默认开；含被拒请求也计数） ----------
time.sleep(65)  # 等限流窗口重置
r = upload("qa-rl.md", VALID_MD.replace("qa-skill", "qa-rate-limit"))
check("B5 限流前上传成功", r.status_code == 201, r.status_code)
rl_id = r.json().get("id") if r.status_code == 201 else None
codes = []
if rl_id:
    for i in range(30):
        rr = httpx.put(BASE + f"/skills/{rl_id}/enabled", headers=H, json={"enabled": i % 2 == 0})
        codes.append(rr.status_code)
    n429 = codes.count(429)
    check("B5 连发写操作出现 429", n429 > 0, f"429x{n429}/30, others={set(codes) - {429}}")
    # 清理
    httpx.delete(BASE + f"/skills/{rl_id}", headers=H)

print("\n=== SUMMARY ===")
fails = [n for n, ok, _ in results if not ok]
print(f"total={len(results)} passed={len(results)-len(fails)} failed={len(fails)}")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
