#!/usr/bin/env python3
"""
ik.me 三位短邮箱可用性筛选（支持多进程并发）。

原理：走真实注册流程（2/4 填表 -> 点 Continue），能进到 3/4 手机验证
就说明前缀可用；卡在 2/4 说明已被占用。全程不填手机号，不会真正建号。

用法：
    python3 screen.py                       # 筛 words.py（单进程，写 result.json）
    python3 screen.py pig cat dog            # 只筛指定的几个
    python3 screen.py --all --workers 8      # 穷举 26^3=17576 种，8 并发
    python3 screen.py --all --workers 8 --email admin@hxsn.eu.cc
                                            # 跑完后把结果发到邮箱（经 Brevo）

多进程时每个 worker 写 result_w{i}.json，全部结束后合并进 result.json。
中断重跑会自动跳过已查过的前缀（分块是确定性的）。
"""
import argparse
import itertools
import json
import multiprocessing as mp
import os
import random
import string
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "https://welcome.infomaniak.com"
SIGNUP = BASE + "/signup/myksuite?referrer=shop"
HERE = os.path.dirname(os.path.abspath(__file__))
RESULT_FILE = os.path.join(HERE, "result.json")
SEND_MAIL = "/root/wula/send_mail.py"  # 复用 wula 项目的 Brevo 发信脚本
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def all_combos():
    return [''.join(c) for c in itertools.product(string.ascii_lowercase, repeat=3)]


def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"available": [], "taken": [], "error": []}


def save_json(data, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def goto_step2(page):
    """回到 2/4 填表页（全新会话）。"""
    page.goto(SIGNUP, timeout=60000)
    page.wait_for_timeout(7000)
    page.click("text=Create a new account")
    page.wait_for_timeout(5000)


def check_one(page, prefix):
    """填表点 Continue，返回 True=可用(进到3/4)，False=被占(卡在2/4)。"""
    page.locator("#input-signup-my-ksuite-username").fill(prefix)
    page.locator("#input-signup-firstname").fill("Test")
    page.locator("#input-signup-lastname").fill("User")
    page.locator("#input-password").fill("T3st!P@ssw0rd#2026")
    page.wait_for_timeout(2500)
    page.click("text=Continue")
    page.wait_for_timeout(7000)
    txt = page.inner_text("body")
    if "3/4" in txt and ("telephone" in txt.lower() or "phone number" in txt.lower()):
        return True
    if "2/4" in txt:
        return False
    raise RuntimeError("页面状态未知: " + txt[:120].replace("\n", " "))


def run_chunk(worker_id, words, out_path):
    """单个 worker：独立浏览器，查完即时写自己的结果文件。"""
    data = load_json(out_path)
    done = set(data["available"]) | set(data["taken"]) | set(data["error"])
    todo = [w for w in words if w not in done]
    print(f"[w{worker_id}] 分配 {len(words)} 个，已查 {len(done)}，本次 {len(todo)}",
          flush=True)
    if not todo:
        return
    consec_err = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            goto_step2(page)
            for i, prefix in enumerate(todo):
                try:
                    ok = check_one(page, prefix)
                    data["available" if ok else "taken"].append(prefix)
                    consec_err = 0
                    print(f"[w{worker_id}][{i+1}/{len(todo)}] {prefix}@ik.me -> "
                          f"{'可用' if ok else '被占'}", flush=True)
                except Exception as e:
                    consec_err += 1
                    data["error"].append(prefix)
                    print(f"[w{worker_id}][{i+1}/{len(todo)}] {prefix}@ik.me -> 出错: {e}",
                          flush=True)
                    if consec_err >= 3:
                        print(f"[w{worker_id}] 连续出错 3 次，暂停 60 秒…", flush=True)
                        time.sleep(60)
                        consec_err = 0
                    try:
                        goto_step2(page)
                    except Exception as e2:
                        print(f"[w{worker_id}] 重建页面失败，退出: {e2}", flush=True)
                        break
                    continue
                save_json(data, out_path)
                if ok:
                    page.click("text=Back")
                    page.wait_for_timeout(4000)
                time.sleep(random.uniform(6, 10))
        finally:
            save_json(data, out_path)
            browser.close()
    print(f"[w{worker_id}] 结束", flush=True)


def merge_results(part_files):
    """把各 worker 的结果并入 result.json（去重）。"""
    base = load_json(RESULT_FILE)
    seen = set(base["available"]) | set(base["taken"]) | set(base["error"])
    for pf in part_files:
        if not os.path.exists(pf):
            continue
        d = load_json(pf)
        for k in ("available", "taken", "error"):
            for w in d[k]:
                if w not in seen:
                    seen.add(w)
                    base[k].append(w)
    save_json(base, RESULT_FILE)
    return base


def send_email(to, data):
    avail = sorted(set(data["available"]))
    subject = f"ik.me 三位前缀筛查完成（可用 {len(avail)} 个）"
    text = "\n".join([
        "ik.me 三位前缀筛查已完成（17576 种全量，含之前查过的 322 个单词）。",
        f"可用: {len(avail)} 个",
        f"被占: {len(data['taken'])} 个",
        f"出错: {len(data['error'])} 个",
        "",
        "可用列表：",
        ", ".join(w + "@ik.me" for w in avail),
    ])
    r = subprocess.run(
        [sys.executable, SEND_MAIL, "--to", to, "--subject", subject,
         "--text", text, "--sender-name", "ikme-check"],
        capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    print("发信结果:", out[-300:], flush=True)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="穷举全部 17576 种组合")
    ap.add_argument("--workers", type=int, default=1, help="并发 worker 数")
    ap.add_argument("--email", default=None, help="跑完后把结果发到该邮箱")
    ap.add_argument("prefixes", nargs="*", help="指定要查的前缀")
    args = ap.parse_args()

    if args.all:
        targets = all_combos()
    elif args.prefixes:
        targets = args.prefixes
    else:
        from words import WORDS
        targets = list(WORDS)

    base = load_json(RESULT_FILE)
    done = set(base["available"]) | set(base["taken"]) | set(base["error"])
    targets = [w for w in targets if w not in done]
    print(f"目标 {len(targets) + len(done)} 个，已查 {len(done)}，本次 {len(targets)}",
          flush=True)

    n = max(1, args.workers)
    if not targets:
        print("全部已查，无需运行。", flush=True)
        return

    if n == 1:
        run_chunk(0, targets, RESULT_FILE)
    else:
        chunks = [targets[i::n] for i in range(n)]
        part_files = [os.path.join(HERE, f"result_w{i}.json") for i in range(n)]
        procs = []
        for i in range(n):
            p = mp.Process(target=run_chunk, args=(i, chunks[i], part_files[i]))
            p.start()
            procs.append(p)
        for p in procs:
            p.join()
        data = merge_results(part_files)
        for pf in part_files:
            if os.path.exists(pf):
                os.remove(pf)
        print(f"合并完成：可用 {len(data['available'])}，"
              f"被占 {len(data['taken'])}，出错 {len(data['error'])}", flush=True)
        if args.email:
            ok = send_email(args.email, data)
            print("邮件已发送" if ok else "邮件发送失败", flush=True)


if __name__ == "__main__":
    main()
