#!/usr/bin/env python3
"""Generate a Markdown quality report from JSONL event logs.

Reads all *.jsonl files from ~/.campus_nav_logs/ (or specified directory)
and produces a summary report with:
  - Session overview
  - Tool execution stats (count, success rate, avg time)
  - Navigation performance (success/fail, avg time per location)
  - Interaction summary (fast path vs LLM, avg response time)
  - Error log

Usage:
    python3 gen_quality_report.py                    # default log dir
    python3 gen_quality_report.py /path/to/logs      # custom log dir
    python3 gen_quality_report.py --latest            # most recent session only
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".campus_nav_logs"


def _load_events(log_dir: str, latest_only: bool = False) -> list[dict]:
    p = Path(log_dir)
    if not p.exists():
        return []
    files = sorted(p.glob("*.jsonl"))
    if latest_only and files:
        files = [files[-1]]
    events = []
    for f in files:
        for line in f.read_text().strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def generate_report(log_dir: str, latest_only: bool = False) -> str:
    events = _load_events(log_dir, latest_only)
    lines = ["# Quality Report", ""]

    if not events:
        lines.append("**No events found.** Run the robot to generate data.")
        return "\n".join(lines)

    # Session overview
    sessions = defaultdict(list)
    for e in events:
        sessions[e.get("session_id", "unknown")].append(e)

    lines.append(f"**Sessions:** {len(sessions)}  ")
    for sid, sevts in sessions.items():
        ts_list = [e["ts"] for e in sevts if "ts" in e]
        t0 = min(ts_list) if ts_list else "?"
        t1 = max(ts_list) if ts_list else "?"
        lines.append(f"- `{sid}`: {len(sevts)} events ({t0[:19]} — {t1[:19]})")
    lines.append("")

    # Tool execution stats
    tool_execs = [e for e in events if e["event"] == "tool_exec"]
    tool_errors = [e for e in events if e["event"] == "tool_error"]

    lines.append("## Tool Execution Summary")
    lines.append("")

    if tool_execs or tool_errors:
        by_tool = defaultdict(lambda: {"success": 0, "fail": 0, "times": []})
        for e in tool_execs:
            d = e["data"]
            tool = d.get("tool", "unknown")
            status = d.get("status", "")
            elapsed = d.get("elapsed_s", 0)
            by_tool[tool]["times"].append(elapsed)
            if status in ("arrived", "spoken", "ok", "success", "cleared", "cancelled",
                          "no_navigation_active", "partial"):
                by_tool[tool]["success"] += 1
            else:
                by_tool[tool]["fail"] += 1

        for e in tool_errors:
            d = e["data"]
            tool = d.get("tool", "unknown")
            by_tool[tool]["fail"] += 1
            elapsed = d.get("elapsed_s", 0)
            if elapsed:
                by_tool[tool]["times"].append(elapsed)

        lines.append("| Tool | Calls | Success | Fail | Rate | Avg Time |")
        lines.append("|------|-------|---------|------|------|----------|")
        for tool, stats in sorted(by_tool.items()):
            total = stats["success"] + stats["fail"]
            rate = f"{stats['success']}/{total}" if total else "—"
            pct = f" ({100 * stats['success'] / total:.0f}%)" if total else ""
            avg_t = f"{sum(stats['times']) / len(stats['times']):.2f}s" if stats["times"] else "—"
            lines.append(f"| {tool} | {total} | {stats['success']} | {stats['fail']} | {rate}{pct} | {avg_t} |")
        lines.append("")
    else:
        lines.append("No tool executions recorded.")
        lines.append("")

    # Navigation performance
    nav_execs = [e for e in tool_execs if e["data"].get("tool") == "navigate_to"]
    if nav_execs:
        lines.append("## Navigation Performance")
        lines.append("")
        by_target = defaultdict(lambda: {"arrived": 0, "failed": 0, "times": []})
        for e in nav_execs:
            d = e["data"]
            target = d.get("input", {}).get("location_name", "unknown") if isinstance(d.get("input"), dict) else "unknown"
            elapsed = d.get("elapsed_s", 0)
            if d.get("status") == "arrived":
                by_target[target]["arrived"] += 1
                by_target[target]["times"].append(elapsed)
            else:
                by_target[target]["failed"] += 1

        lines.append("| Target | Arrived | Failed | Avg Time |")
        lines.append("|--------|---------|--------|----------|")
        for target, stats in sorted(by_target.items()):
            avg_t = f"{sum(stats['times']) / len(stats['times']):.1f}s" if stats["times"] else "—"
            lines.append(f"| {target} | {stats['arrived']} | {stats['failed']} | {avg_t} |")
        lines.append("")

    # Interaction summary
    interactions = [e for e in events if e["event"] == "interaction"]
    if interactions:
        lines.append("## Interaction Summary")
        lines.append("")
        by_path = defaultdict(lambda: {"count": 0, "times": []})
        for e in interactions:
            d = e["data"]
            path = d.get("path", "unknown")
            by_path[path]["count"] += 1
            by_path[path]["times"].append(d.get("elapsed_s", 0))

        total_i = sum(v["count"] for v in by_path.values())
        lines.append(f"**Total interactions:** {total_i}  ")
        lines.append("")
        lines.append("| Path | Count | Avg Response Time |")
        lines.append("|------|-------|-------------------|")
        for path, stats in sorted(by_path.items()):
            avg_t = f"{sum(stats['times']) / len(stats['times']):.2f}s" if stats["times"] else "—"
            lines.append(f"| {path} | {stats['count']} | {avg_t} |")
        lines.append("")

    # Errors
    all_errors = tool_errors + [e for e in events if e["event"] == "handle_error"]
    if all_errors:
        lines.append("## Errors")
        lines.append("")
        lines.append("| Time | Type | Detail |")
        lines.append("|------|------|--------|")
        for e in all_errors:
            ts = e.get("ts", "?")[:19]
            d = e["data"]
            etype = e["event"]
            detail = d.get("error", "")
            tool = d.get("tool", d.get("input", ""))
            lines.append(f"| {ts} | {etype} | **{tool}**: {detail} |")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from `{log_dir}`*")

    return "\n".join(lines)


def main():
    latest_only = "--latest" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    log_dir = args[0] if args else str(_DEFAULT_LOG_DIR)

    report = generate_report(log_dir, latest_only=latest_only)
    print(report)

    out = Path(log_dir) / "quality_report.md"
    out.write_text(report)
    print(f"\nReport saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
