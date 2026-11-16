#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键评测 driver —— 依次运行三套评测，实时打印进度、逐题 pass/fail 与分数，最后汇总。

三套评测：
  1) locomo  (LoCoMo-Plus 长对话记忆)      -> benchmarks/csm_locomo_plus.py
  2) bench22 (陪伴型中文记忆 Benchmark 2.2)-> benchmarks/run_csm_bench22.py
  3) pair    (WSC vs DSH 原生压缩对比)     -> .local/goal-wsc-paid-20261111/host_pair.py

设计要点：
  * 以本文件所在目录为评测根目录 (ROOT)，所有相对路径都基于它，故整个 evals/ 可整体搬迁。
  * 不改动任何评测源脚本；通过环境变量注入 API 配置；host_pair 的硬编码 node 路径
    在运行时生成一份临时副本 _host_pair.local.py（只替换 NODE/CLI 两行），跑完即删。
  * 逐题结果的字段在三套里不同：locomo=judge.label, bench22=judgments.jsonl 的 pass/points,
    pair=result.score.tests[].ok。分别处理，不混用。
  * key 只从 config.json / 环境变量读取，绝不写死在代码或公开仓库里。

用法：
  python eval_driver.py                      # 按 config.json 运行
  python eval_driver.py --only locomo        # 只跑某一套 (locomo|bench22|pair)
  python eval_driver.py --demo               # 不调用 API，仅用已有结果演示"逐题打印"格式
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_PATH = ROOT / "config.example.json"
RESULTS = ROOT / "run_results"
RESULTS.mkdir(exist_ok=True)

# ---------- 终端输出工具（Windows 中文兼容） ----------
def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        print(*(str(a).encode("utf-8", "replace").decode("utf-8", "replace") for a in args), **kwargs)


def flush():
    try:
        sys.stdout.flush()
    except Exception:
        pass


LINE = "=" * 72
SUB = "-" * 72


def banner(title: str):
    _safe_print("\n" + LINE)
    _safe_print("  " + title)
    _safe_print(LINE)
    flush()


def status(tag: str, msg: str):
    _safe_print(f"[{tag}] {msg}")
    flush()


# ---------- 配置 ----------
DEFAULTS = {
    "api": {"base_url": "http://127.0.0.1:8788/v1", "model": "deepseek-v4.1-flash", "api_key": ""},
    "node": {"node_bin": "E:/nodejs/node.exe",
             "dsh_cli": "E:/nodejs/node_modules/@deepseek-ai/dsh/lib/bin.js"},
    "python": {"venv_python": ""},
    "run": {"locomo": True, "bench22": True, "pair": True,
            "locomo_mode": "qa", "locomo_conversation": 0, "locomo_samples": 20,
            "bench22_stages": ["prepare", "gateway", "exam", "judge"],
            "pair_stage": "prepare_and_run"},
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            status("WARN", f"config.json 解析失败，使用默认值: {e}")
    else:
        status("WARN", "未找到 config.json，使用默认配置（请先复制 config.example.json 为 config.json）")
    return cfg


def resolve_python(cfg: dict) -> str:
    p = cfg["python"].get("venv_python") or ""
    if p and Path(p).exists():
        return p
    return sys.executable


def build_env(cfg: dict) -> dict:
    """构造子进程环境：清掉注入的 PYTHONPATH，注入 API 配置。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = ""           # 规避本机 WorkBuddy shim 导致的子进程 SystemExit
    env["PYTHONIOENCODING"] = "utf-8"
    api = cfg["api"]
    if api.get("base_url"):
        env["CSM_BENCH_BASE_URL"] = str(api["base_url"]).rstrip("/")
    if api.get("model"):
        env["CSM_BENCH_MODEL"] = str(api["model"])
    if api.get("api_key"):
        env["CSM_BENCH_API_KEY"] = str(api["api_key"])
        env["WD_API_KEY"] = str(api["api_key"])
        env["DASHSCOPE_API_KEY"] = str(api["api_key"])
    return env


def run_cmd(cmd, cwd: Path, env: dict, timeout: int | None = None) -> int:
    """运行子进程，实时转发 stdout/stderr 作为进度。"""
    status("RUN", " ".join(str(c) for c in cmd))
    started = time.time()
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _safe_print("    | " + line.rstrip())
            flush()
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        status("TIMEOUT", f"超过 {timeout}s，终止")
        proc.kill()
        code = -1
    except Exception as e:
        status("ERROR", f"启动失败: {e}")
        code = -1
    status("DONE", f"退出码 {code}，用时 {time.time() - started:.1f}s")
    return code


# ---------- 逐题打印 ----------
SCORES = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}


def fmt_result(ok: bool, score: float) -> str:
    mark = "PASS" if ok else "FAIL"
    return f"[{mark}] score={score:.2f}"


def print_locomo(out_json: Path | None) -> dict:
    banner("评测结果 · LoCoMo-Plus (长对话记忆)")
    if not out_json or not out_json.exists():
        status("WARN", f"未找到结果文件 {out_json}，跳过逐题打印")
        return {"name": "locomo", "available": False}
    data = json.loads(out_json.read_text(encoding="utf-8"))
    records = data.get("records", [])
    summary = data.get("summary", {})
    total = 0.0
    passed = 0
    for i, r in enumerate(records, 1):
        label = (r.get("judge") or {}).get("label", "wrong")
        score = SCORES.get(label, 0.0)
        ok = label != "wrong"
        total += score
        passed += int(ok)
        cat = r.get("category", "-")
        q = str(r.get("question", ""))[:60].replace("\n", " ")
        _safe_print(f"  {i:>4}. {fmt_result(ok, score):<18} [{cat:<12}] {q}")
    flush()
    n = len(records) or 1
    acc = summary.get("accuracy", total / n)
    _safe_print(SUB)
    _safe_print(f"  逐题: {passed}/{len(records)} 通过（partial 计半对） | 平均分 {total/n:.4f} | 报告 accuracy={acc}")
    _safe_print(f"  分类: {json.dumps(summary.get('by_category', {}), ensure_ascii=False)}")
    return {"name": "locomo", "available": True, "total": len(records), "passed": passed,
            "mean": total / n, "accuracy": acc}


def print_bench22(runs_dir: Path) -> dict:
    banner("评测结果 · 陪伴型记忆 Benchmark 2.2")
    judgments = sorted(runs_dir.rglob("judgments.jsonl"))
    if not judgments:
        status("WARN", f"未在 {runs_dir} 找到 judgments.jsonl，跳过逐题打印")
        return {"name": "bench22", "available": False}
    # 取最新修改的一份
    jf = max(judgments, key=lambda p: p.stat().st_mtime)
    try:
        _shown = str(jf.relative_to(ROOT))
    except ValueError:
        _shown = str(jf)
    status("INFO", f"逐题结果文件: {_shown}")
    rows = []
    for line in jf.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    total = 0.0
    passed = 0
    for i, r in enumerate(rows, 1):
        # 兼容两套 schema：
        #   旧: pass(bool) + points(float)
        #   新: score(float 0/1) + judge{...}
        if "pass" in r or "points" in r:
            ok = bool(r.get("pass"))
            score = float(r.get("points", 0.0) or 0.0)
        else:
            score = float(r.get("score", 0.0) or 0.0)
            ok = score > 0
        total += score
        passed += int(ok)
        qid = str(r.get("id", "-"))
        _safe_print(f"  {i:>4}. {fmt_result(ok, score):<18} {qid}")
    flush()
    n = len(rows) or 1
    _safe_print(SUB)
    _safe_print(f"  逐题: {passed}/{len(rows)} 通过 | 平均分 {total/n:.4f}")
    # 附带 summary.json 的 boards（若有）
    for s in sorted(runs_dir.rglob("summary.json"), key=lambda p: p.stat().st_mtime)[-1:]:
        try:
            boards = json.loads(s.read_text(encoding="utf-8")).get("boards", {})
            _safe_print(f"  boards: {json.dumps(boards, ensure_ascii=False)[:600]}")
        except Exception:
            pass
    return {"name": "bench22", "available": True, "total": len(rows), "passed": passed, "mean": total / n}


def print_pair(result_jsons: list[Path]) -> dict:
    banner("评测结果 · WSC vs DSH 原生压缩对比")
    if not result_jsons:
        status("WARN", "未找到 *-result.json，跳过逐题打印")
        return {"name": "pair", "available": False}
    out = []
    for rf in result_jsons:
        data = json.loads(rf.read_text(encoding="utf-8"))
        score = data.get("score", {})
        tests = score.get("tests", [])
        _safe_print(f"\n  >>> {rf.name}  (exit={data.get('exit_code')}, {data.get('seconds', 0):.1f}s)")
        p = 0
        for i, t in enumerate(tests, 1):
            ok = bool(t.get("ok"))
            p += int(ok)
            _safe_print(f"    {i:>3}. {fmt_result(ok, 1.0 if ok else 0.0):<18} {t.get('name','')}")
        _safe_print(f"  {SUB}")
        _safe_print(f"  汇总: {score.get('passed')}/{score.get('total')} 通过, score={score.get('score')}")
        out.append({"file": rf.name, "total": score.get("total"), "passed": score.get("passed"),
                    "score": score.get("score")})
    flush()
    return {"name": "pair", "available": True, "arms": out}


# ---------- 各套运行 ----------
def run_locomo(cfg: dict, env: dict) -> Path | None:
    banner("开始评测 1/3 · LoCoMo-Plus")
    py = resolve_python(cfg)
    runcfg = cfg["run"]
    mode = runcfg.get("locomo_mode", "qa")
    out = RESULTS / f"locomo-{mode}.json"
    db = RESULTS / f"locomo-{mode}.db"
    cmd = [py, str(ROOT / "benchmarks" / "csm_locomo_plus.py"), mode]
    if mode == "qa":
        cmd += ["--conversation", str(runcfg.get("locomo_conversation", 0))]
    else:
        cmd += ["--samples", str(runcfg.get("locomo_samples", 20))]
    cmd += ["--out", str(out), "--db", str(db)]
    run_cmd(cmd, ROOT, env)
    return out if out.exists() else None


def run_bench22(cfg: dict, env: dict) -> Path:
    banner("开始评测 2/3 · 陪伴型记忆 Benchmark 2.2")
    py = resolve_python(cfg)
    entry = ROOT / "benchmarks" / "run_csm_bench22.py"
    stages = cfg["run"].get("bench22_stages") or ["prepare", "gateway", "exam", "judge"]
    for stage in stages:
        status("STAGE", f"bench22 :: {stage}")
        # gateway 是长驻服务：单独提示用户在该阶段由脚本自行起（脚本 serve() 内部处理）
        rc = run_cmd([py, str(entry), stage], ROOT, env)
        if rc != 0 and stage != "gateway":
            status("WARN", f"阶段 {stage} 返回 {rc}，继续后续阶段")
    return ROOT / ".local" / "bench22-public-20261111" / "runs" / "bench22"


def make_local_host_pair(cfg: dict) -> Path | None:
    """生成 host_pair 的运行时副本，仅替换硬编码的 NODE/CLI，避免改动交付源脚本。"""
    src = ROOT / ".local" / "goal-wsc-paid-20261111" / "host_pair.py"
    if not src.exists():
        return None
    node = str(cfg["node"].get("node_bin", "")).replace("\\", "/")
    cli = str(cfg["node"].get("dsh_cli", "")).replace("\\", "/")
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"^NODE\s*=.*$", f"NODE = Path({node!r})", text, count=1, flags=re.M)
    text = re.sub(r"^CLI\s*=.*$", f"CLI = Path({cli!r})", text, count=1, flags=re.M)
    # 修正 ROOT：源脚本用 HERE.parents[2]，打包/单独解压时层级会变，
    # 这里显式指向评测根目录 (ROOT)，使 J=ROOT/dsh-wsc、SOURCE=J/experiments 成立。
    text = re.sub(r"^ROOT\s*=.*$", f"ROOT = Path({str(ROOT)!r})", text, count=1, flags=re.M)
    dst = src.parent / "_host_pair.local.py"
    dst.write_text(text, encoding="utf-8")
    return dst


def run_pair(cfg: dict, env: dict) -> list[Path]:
    banner("开始评测 3/3 · WSC vs DSH 原生压缩对比")
    py = resolve_python(cfg)
    base = ROOT / ".local" / "goal-wsc-paid-20261111"
    local = make_local_host_pair(cfg)
    if local is None:
        status("WARN", "host_pair.py 缺失，跳过")
        return []
    # 用隔离 stage 跑，避免污染已有结果
    stage = "host-pair-auto"
    stage_dir = base / stage
    status("INFO", f"隔离 stage: {stage_dir}")
    # prepare（若已存在则跳过）
    if not (stage_dir / "setup.json").exists():
        rc = run_cmd([py, str(local), "prepare", "--stage", stage, "--isolated-home",
                      "--fixture", "hard", "--dedupe-carried-state", "--serial"], base, env)
        if rc != 0:
            status("ERROR", "pair prepare 失败，跳过 run")
            return []
    rc = run_cmd([py, str(local), "run", "--stage", stage, "--isolated-home", "--serial"], base, env)
    status("INFO", f"pair run 退出码={rc}（18/18 但 exit!=0 也可能是尾部综述截断，详见六指标报告）")
    # 清理临时副本
    try:
        local.unlink()
    except Exception:
        pass
    return sorted(stage_dir.glob("*-result.json"))


# ---------- 汇总 ----------
def write_summary(results: list[dict]):
    banner("总汇总")
    _safe_print(f"{'评测':<26}{'通过':<14}{'平均分':<14}")
    _safe_print(SUB)
    for r in results:
        if not r.get("available"):
            _safe_print(f"{r['name']:<26}{'(未运行/无结果)':<14}{'-':<14}")
            continue
        if r["name"] == "pair":
            for arm in r.get("arms", []):
                _safe_print(f"  pair/{arm['file']:<20}{str(arm['passed'])+'/'+str(arm['total']):<14}{str(arm.get('score')):<14}")
        else:
            _safe_print(f"{r['name']:<26}{str(r['passed'])+'/'+str(r['total']):<14}{r.get('mean', 0):<14.4f}")
    _safe_print(LINE)
    report = RESULTS / "summary.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    status("INFO", f"机器可读汇总已写入 {report.relative_to(ROOT)}")


def do_demo():
    """仅用已有结果演示逐题打印格式，不调用 API。"""
    status("DEMO", "使用已有结果文件演示逐题打印（不调用 API）")
    results = []
    wsc = "D:/lea/XenYon code/wsc"
    p1 = Path(wsc) / "benchmarks" / "results" / "locomo-atomic2.json"
    results.append(print_locomo(p1 if p1.exists() else None))
    runs = Path(wsc) / ".local" / "bench22-public-20261111" / "runs" / "bench22"
    results.append(print_bench22(runs))
    pr = sorted((Path(wsc) / ".local" / "goal-wsc-paid-20261111").glob("host-pair-v21-isolated/*-result.json"))
    results.append(print_pair(pr))
    write_summary(results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["locomo", "bench22", "pair"])
    ap.add_argument("--demo", action="store_true", help="仅用已有结果演示打印格式")
    args = ap.parse_args()

    banner("WSC / CSM 一键评测 driver")
    status("INFO", f"评测根目录 ROOT = {ROOT}")
    if args.demo:
        do_demo()
        return

    cfg = load_config()
    env = build_env(cfg)
    api = cfg["api"]
    status("INFO", f"API base_url = {api.get('base_url')}  model = {api.get('model')}")
    status("INFO", f"API key = {'已配置' if api.get('api_key') else '未配置（走本地凭据/默认）'}")

    results = []
    only = args.only
    if only in (None, "locomo") and cfg["run"].get("locomo", True):
        try:
            out = run_locomo(cfg, env)
            results.append(print_locomo(out))
        except Exception as e:
            status("ERROR", f"locomo 异常: {e}")
            results.append({"name": "locomo", "available": False})
    if only in (None, "bench22") and cfg["run"].get("bench22", True):
        try:
            runs = run_bench22(cfg, env)
            results.append(print_bench22(runs))
        except Exception as e:
            status("ERROR", f"bench22 异常: {e}")
            results.append({"name": "bench22", "available": False})
    if only in (None, "pair") and cfg["run"].get("pair", True):
        try:
            rjs = run_pair(cfg, env)
            results.append(print_pair(rjs))
        except Exception as e:
            status("ERROR", f"pair 异常: {e}")
            results.append({"name": "pair", "available": False})
    write_summary(results)


if __name__ == "__main__":
    main()
