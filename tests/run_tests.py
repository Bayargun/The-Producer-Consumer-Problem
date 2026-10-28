#!/usr/bin/env python3
"""run_tests.py - бүх туршилтыг нэг командаар ажиллуулна.

Хэрэглээ (төслийн үндсэн хавтаснаас):
    python3 tests/run_tests.py              # бүгд
    python3 tests/run_tests.py B1 C3        # сонгосон тохиолдлууд
    python3 tests/run_tests.py --cases tests/my_cases.csv

Хийх зүйлс:
  1. C кодыг -Wall -Wextra -Werror-тэй хөрвүүлнэ
  2. tests/test_buffer.c unit тестийг ажиллуулна
  3. tests/cases.csv-ийн тохиолдол бүрийг ажиллуулж, хүлээгдэх үр дүнтэй харьцуулна
  4. Үр дүнг tests/results.md хүснэгт, tests/logs/*.jsonl.gz лог болгон хадгална
"""
import argparse
import gzip
import json
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
PC = os.path.join(ROOT, "pc")
LOGS = os.path.join(TESTS, "logs")
MAX_LOG_LINES = 20000          # хадгалах лог-ийн дээд мөр


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- build/unit
def build():
    r = sh(["gcc", "-Wall", "-Wextra", "-Werror", "-pthread",
            "src/buffer.c", "src/main.c", "-o", "pc"])
    if r.returncode != 0:
        print("ХӨРВҮҮЛЭЛТ АМЖИЛТГҮЙ:\n" + r.stderr)
        sys.exit(1)
    r2 = sh(["gcc", "-Wall", "-Wextra", "-Werror", "-pthread",
             "src/buffer.c", "tests/test_buffer.c", "-o", "tests/test_buffer"])
    if r2.returncode != 0:
        print("test_buffer хөрвүүлэлт амжилтгүй:\n" + r2.stderr)
        sys.exit(1)


def unit_tests():
    r = sh(["tests/test_buffer"], timeout=60)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    # init(0), init(65) хоёулаа -1 буцаах ёстой
    ok = r.returncode == 0 and "FAIL" not in r.stdout and \
        sum("PASS" in l for l in lines) == 3 and \
        all("-> -1" in l for l in lines if l.startswith("init("))
    return ok, lines


# ---------------------------------------------------------------- log шинжилгээ
def analyze(lines):
    """JSON мөрүүдээс тоон үзүүлэлт гаргана."""
    ev = [json.loads(l) for l in lines if l.startswith("{")]
    cfg = next(e for e in ev if e["ev"] == "config")
    size = cfg["size"]
    end_t = max(e["t"] for e in ev) or 1
    # хугацаагаар жигнэсэн дундаж дүүргэлт
    area, prev_t, prev_c = 0, 0, 0
    seq = []
    waits = {"P": 0, "C": 0}
    max_c = 0
    for e in ev:
        if e["ev"] in ("produce", "consume"):
            area += prev_c * (e["t"] - prev_t)
            prev_t, prev_c = e["t"], e["count"]
            max_c = max(max_c, e["count"])
            seq.append(e["ev"][0])          # 'p' эсвэл 'c'
        elif e["ev"] == "wait":
            waits[e["who"][0]] += 1
    area += prev_c * (end_t - prev_t)
    mean = area / end_t / size
    alternate = all(seq[i] == ("p" if i % 2 == 0 else "c") for i in range(len(seq)))
    return dict(size=size, events=len(ev), produced=seq.count("p"), consumed=seq.count("c"),
                mean=mean, max=max_c, waitP=waits["P"], waitC=waits["C"], alternate=alternate)


def check_log(text):
    r = sh([sys.executable, "tests/check_log.py"], input=text)
    return r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr


# ---------------------------------------------------------------- тохиолдлууд
def run_case(cid, args, expect):
    argv = args.split()
    t0 = time.monotonic()

    if expect == "usage" or expect.startswith("error:"):
        r = subprocess.run([PC] + argv, capture_output=True, text=True, timeout=10)
        msg = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "(stderr хоосон)"
        if expect == "usage":
            ok = r.returncode == 1 and "Хэрэглээ" in r.stderr
        else:
            ok = r.returncode == 1 and expect[6:] in r.stderr
        return ok, f"exit={r.returncode}: {msg}", None, time.monotonic() - t0

    sleep_sec = int(argv[0])

    if expect == "nohang":
        # stdin-ийг НЭЭЛТТЭЙ үлдээнэ (UI-тай ижил нөхцөл)
        p = subprocess.Popen([PC, "-j"] + argv, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            p.wait(timeout=sleep_sec + 3)
            el = time.monotonic() - t0
            return p.returncode == 0, f"{el:.2f}с-д дууссан (хязгаар {sleep_sec + 3}с)", None, el
        except subprocess.TimeoutExpired:
            p.kill()
            return False, "ГАЦСАН: хугацаандаа дуусаагүй", None, time.monotonic() - t0

    if expect == "speed":
        p = subprocess.Popen([PC, "-j"] + argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        time.sleep(0.5)
        p.stdin.write("prod_ms 50\n"); p.stdin.flush()
        time.sleep(0.5)
        p.stdin.write("hello 5\n"); p.stdin.flush()
        out, _ = p.communicate(timeout=sleep_sec + 5)
        ev = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
        sp = [e for e in ev if e["ev"] == "speed"]
        er = [e for e in ev if e["ev"] == "error"]
        # хурд өөрчлөгдсөний дараа producer ихэссэн эсэх
        t_sp = sp[0]["t"] if sp else 10 ** 9
        before = sum(1 for e in ev if e["ev"] == "produce" and e["t"] < t_sp)
        after = sum(1 for e in ev if e["ev"] == "produce" and e["t"] >= t_sp)
        ok = len(sp) == 1 and sp[0]["prod_ms"] == 50 and len(er) == 1 and after > before
        return ok, (f"speed={len(sp)} error={len(er)}; produce өмнө {before}, "
                    f"дараа {after}"), None, time.monotonic() - t0

    # pass, pass,mean>=X, pass,mean<=X, pass,alternate
    r = subprocess.run([PC, "-j"] + argv, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=sleep_sec + 30)
    lines = r.stdout.splitlines(keepends=True)
    os.makedirs(LOGS, exist_ok=True)
    keep = lines[:MAX_LOG_LINES]      # GitHub-д багтаахын тулд том логийг таслана
    with gzip.open(os.path.join(LOGS, f"{cid}.jsonl.gz"), "wt", encoding="utf-8") as f:
        f.writelines(keep)
    ok, verdict = check_log(r.stdout)  # шалгалтыг БҮТЭН лог дээр хийнэ
    a = analyze(lines)
    a["saved"] = len(keep)
    detail = verdict
    for cond in expect.split(",")[1:]:
        if cond.startswith("mean>="):
            ok &= a["mean"] >= float(cond[6:])
        elif cond.startswith("mean<="):
            ok &= a["mean"] <= float(cond[6:])
        elif cond == "alternate":
            ok &= a["alternate"]
            detail += f"; ээлжлэл={'тийм' if a['alternate'] else 'ҮГҮЙ'}"
    return ok, detail, a, time.monotonic() - t0


def load_cases(path):
    cases = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split(";")
            if len(parts) != 5:
                print(f"{path}:{n}: 5 багана байх ёстой, {len(parts)} байна: {line}")
                sys.exit(2)
            cases.append(dict(zip(["id", "group", "desc", "args", "expect"], parts)))
    return cases


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="зөвхөн эдгээр id-г ажиллуулна")
    ap.add_argument("--cases", default=os.path.join(TESTS, "cases.csv"))
    ap.add_argument("--out", default=os.path.join(TESTS, "results.md"))
    opt = ap.parse_args()

    print("1) Хөрвүүлж байна (-Wall -Wextra -Werror)...")
    build()
    print("   OK")

    print("2) Unit тест (tests/test_buffer.c)...")
    u_ok, u_lines = unit_tests()
    for l in u_lines:
        print("   " + l)

    cases = load_cases(opt.cases)
    if opt.ids:
        cases = [c for c in cases if c["id"] in opt.ids]
    print(f"3) {len(cases)} тохиолдол ({os.path.relpath(opt.cases, ROOT)})...")
    results = []
    for c in cases:
        ok, detail, a, el = run_case(c["id"], c["args"], c["expect"])
        results.append((c, ok, detail, a, el))
        print(f"   {'PASS' if ok else 'FAIL'}  {c['id']:<4} {c['desc']:<48} {detail}")

    # ---- results.md
    n_ok = sum(r[1] for r in results)
    env = (f"{platform.system()} {platform.release()}, "
           f"{sh(['gcc', '--version']).stdout.splitlines()[0]}, "
           f"Python {platform.python_version()}, CPU {os.cpu_count()} цөм")
    md = [f"# Туршилтын үр дүн",
          "",
          f"- Огноо: {time.strftime('%Y-%m-%d %H:%M')}",
          f"- Орчин: {env}",
          f"- Unit тест: {'PASS' if u_ok else 'FAIL'}",
          f"- Тохиолдол: **{n_ok}/{len(results)} PASS**",
          "",
          "| ID | Бүлэг | Тайлбар | Аргумент | Хүлээгдэх | Үр дүн | Дэлгэрэнгүй |",
          "|---|---|---|---|---|---|---|"]
    for c, ok, detail, a, el in results:
        md.append(f"| {c['id']} | {c['group']} | {c['desc']} | `{c['args'] or '—'}` | "
                  f"{c['expect']} | {'✅ PASS' if ok else '❌ FAIL'} | {detail} |")
    md += ["", "## Ажиллагааны үзүүлэлт (JSON лог-оос)", "",
           "| ID | size | event | produced | consumed | дундаж дүүргэлт | max | wait (P) | wait (C) | хадгалсан лог |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for c, ok, detail, a, el in results:
        if a:
            saved = "бүтэн" if a["saved"] >= a["events"] else f"эхний {a['saved']} мөр"
            md.append(f"| {c['id']} | {a['size']} | {a['events']} | {a['produced']} | "
                      f"{a['consumed']} | {a['mean'] * 100:.0f}% | {a['max']} | {a['waitP']} | "
                      f"{a['waitC']} | {saved} |")
    md += ["", "Лог файлууд: `tests/logs/<ID>.jsonl.gz` "
           "(`zcat tests/logs/B1.jsonl.gz | python3 tests/check_log.py` гэж дахин шалгана)."]
    with open(opt.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"\nДүн: unit={'PASS' if u_ok else 'FAIL'}, тохиолдол {n_ok}/{len(results)} PASS")
    print(f"Хүснэгт: {os.path.relpath(opt.out, ROOT)}")
    return 0 if u_ok and n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())