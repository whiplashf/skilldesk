"""One user-initiated, library-wide version check per running Skilldesk service."""

import logging
import threading
import time

from fastapi import BackgroundTasks, HTTPException


class LibraryUpdateCheck:
    def __init__(self):
        self._lock = threading.Lock()
        self._report: dict | None = None
        self._applied: dict[tuple[str, str, str], dict] = {}

    def snapshot(self) -> dict | None:
        with self._lock:
            if self._report is None:
                return None
            return {
                **self._report,
                "updates": self._report["updates"].copy(),
                "failures": self._report["failures"].copy(),
            }

    @staticmethod
    def _update_row(row, status):
        return {**row, "status": "release", "latest": status["latest"], "release": status["release"],
                "entries": status.get("entries", [])}

    def applied(self, key: str, release: dict, remaining: dict | None) -> None:
        with self._lock:
            if self._report is None:
                return
            edition = (key, release["tag"], release["commit"])
            self._applied[edition] = remaining or {}
            updates = []
            for row in self._report["updates"]:
                if (row["key"], row["latest"], row["release"]["commit"]) != edition:
                    updates.append(row)
                elif remaining and remaining["status"] == "release":
                    updates.append(self._update_row(row, remaining))
            self._report["updates"] = updates

    def start(self, tasks: BackgroundTasks, inventory, check) -> dict:
        with self._lock:
            if self._report is None or not self._report["running"]:
                self._applied.clear()
                self._report = {
                    "running": True, "finishedAt": 0, "total": None, "untracked": 0,
                    "checked": 0, "uncertain": 0, "noRelease": 0, "updates": [], "failures": [], "error": "",
                }
                tasks.add_task(self._run, self._report, inventory, check)
        return self.snapshot()

    def _run(self, report: dict, inventory, check):
        try:
            targets, untracked = inventory()
            with self._lock:
                report.update(total=len(targets), untracked=untracked)
            batch = {}
            for item, source in targets:
                row = {"key": item["identity_key"], "name": item["name"],
                       "repo": source["repo"], "path": source["path"]}
                try:
                    result = check(item, source, force=True, batch=batch)
                except HTTPException as exc:
                    with self._lock:
                        report["failures"].append({**row, "detail": str(exc.detail)})
                        if exc.status_code == 429:
                            report["error"] = str(exc.detail)
                            break
                    continue
                with self._lock:
                    status = result["status"]
                    report["checked"] += 1
                    if status == "release":
                        edition = (row["key"], result["latest"], result["release"]["commit"])
                        pending = self._applied.get(edition, result)
                        if pending.get("status") == "release":
                            report["updates"].append(self._update_row(row, pending))
                    elif status == "no_release":
                        report["noRelease"] += 1
                    elif status == "unknown":
                        report["uncertain"] += 1
        except Exception:
            logging.getLogger(__name__).exception("全库版本检查中断")
            with self._lock:
                report["error"] = "全库检查中断，已完成的结果已保留。请重新检查。"
        finally:
            with self._lock:
                report.update(running=False, finishedAt=int(time.time()))
