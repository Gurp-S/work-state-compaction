"""No-inference probe of the actual native account and session entrypoint."""
import argparse
import json
from pathlib import Path

from native_rpc import NativeRPC


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    work = root / "workspace"
    work.mkdir()
    report = {"executable": args.executable, "requested_model": "gpt-6-luna",
              "requested_effort": "max", "inference_requested": False,
              "global_configuration_changed": False, "stage": "launch"}
    try:
        with NativeRPC(args.executable, cwd=work, stderr_path=root / "stderr.txt",
                       settings=['features.multi_agent=false', 'model_reasoning_effort="max"']) as server:
            report["stage"] = "initialize"
            initialized = server.call("initialize", {"clientInfo": {"name": "independent_wsc_benefit", "version": "0.1"},
                                                     "capabilities": {"experimentalApi": True}})
            report["server_version"] = initialized.get("userAgent")
            server.send({"method": "initialized"})
            report["stage"] = "account/read"
            account = server.call("account/read", {"refreshToken": False})
            report["account_type"] = (account.get("account") or {}).get("type")
            report["requires_openai_auth"] = account.get("requiresOpenaiAuth")
            report["stage"] = "thread/start"
            opened = server.call("thread/start", {"cwd": str(work), "model": "gpt-6-luna",
                                                   "approvalPolicy": "never", "sandbox": "workspace-write",
                                                   "ephemeral": False})
            report["thread_id"] = opened["thread"]["id"]
            report["actual_model"] = opened.get("model")
            report["actual_effort"] = opened.get("reasoningEffort")
            report["rollout_path"] = opened["thread"].get("path")
            report["stage"] = "native_session_opened_no_inference"
            report["ready"] = opened.get("model") == "gpt-6-luna" and opened.get("reasoningEffort") == "max"
    except Exception as exc:
        report["ready"] = False
        report["error"] = type(exc).__name__ + ": " + str(exc)
    (root / "preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
