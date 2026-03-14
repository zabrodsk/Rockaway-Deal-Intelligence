"""Dedicated Specter batch worker.

This process runs outside the web service and keeps long-running Specter batch
coordination out of the Railway web process. Company evaluation still happens
in per-company subprocesses so memory is reclaimed aggressively.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import traceback
from typing import Any

from agent.ingest.specter_ingest import ingest_specter_company, list_specter_companies
from web import app as web_app
import web.db as db

EVENT_PREFIX = "__SPECTER_COMPANY_EVENT__"
POLL_SECONDS = max(1, int(os.getenv("SPECTER_WORKER_POLL_SECONDS", "5")))


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _normalize_company_key(name: str | None, slug: str | None) -> str:
    return f"{(slug or name or 'unknown').strip().lower()}"


def _write_worker_config(
    work_dir: Path,
    *,
    job_id: str,
    absolute_index: int,
    run_config: dict[str, Any],
    versions: dict[str, Any],
) -> Path:
    path = work_dir / f".specter-worker-{job_id}-{absolute_index}.json"
    path.write_text(
        json.dumps({"run_config": run_config, "versions": versions}, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def _load_completed_company_keys(job_id: str) -> tuple[set[str], int, int]:
    rows = db.load_job_company_runs(job_id)
    completed: set[str] = set()
    failed = 0
    for row in rows:
        key = _normalize_company_key(row.get("company_name"), row.get("startup_slug"))
        completed.add(key)
        if str(row.get("decision") or "").strip().lower() in {"error", "timeout"}:
            failed += 1
    return completed, max(0, len(completed) - failed), failed


def _specter_files_from_run_config(
    run_config: dict[str, Any],
    source_files: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    manifest = run_config.get("specter_worker_files") or {}
    companies_storage_path = manifest.get("companies_storage_path")
    people_storage_path = manifest.get("people_storage_path")
    if companies_storage_path:
        return companies_storage_path, people_storage_path

    companies_name = manifest.get("companies_name")
    people_name = manifest.get("people_name")
    for file_info in source_files:
        if not companies_storage_path and file_info.get("name") == companies_name:
            companies_storage_path = file_info.get("storage_path")
        if people_name and not people_storage_path and file_info.get("name") == people_name:
            people_storage_path = file_info.get("storage_path")
    return companies_storage_path, people_storage_path


def _download_worker_inputs(job_id: str, run_config: dict[str, Any]) -> tuple[Path, Path, Path | None]:
    source_files = db.load_source_files(job_id)
    companies_storage_path, people_storage_path = _specter_files_from_run_config(run_config, source_files)
    if not companies_storage_path:
        raise RuntimeError("Missing shared Specter company export for worker-backed job.")

    work_dir = Path(tempfile.mkdtemp(prefix=f"specter-worker-{job_id}-"))
    companies_path = work_dir / "companies.csv"
    if not db.download_source_file_to_path(companies_storage_path, companies_path):
        raise RuntimeError("Failed to download shared Specter company export.")

    people_path: Path | None = None
    if people_storage_path:
        people_path = work_dir / "people.csv"
        if not db.download_source_file_to_path(people_storage_path, people_path):
            raise RuntimeError("Failed to download shared Specter people export.")

    return work_dir, companies_path, people_path


def _failure_result(
    job_id: str,
    *,
    company: Any,
    store: Any,
    slug: str,
    error_message: str,
    status: str,
) -> dict[str, Any]:
    web_app._results_cache[job_id] = web_app._results_cache.get(job_id, {})
    return web_app._failure_result_payload(
        job_id,
        company=company,
        store=store,
        slug=slug,
        status=status,
        error_message=error_message,
    )


def _persist_subprocess_failure(
    job_id: str,
    *,
    companies_csv: Path,
    people_csv: Path | None,
    company_index: int,
    run_config: dict[str, Any],
    versions: dict[str, Any],
    error_message: str,
) -> None:
    company, store = ingest_specter_company(companies_csv, people_csv, company_index=company_index)
    status = "error"
    payload = _failure_result(
        job_id,
        company=company,
        store=store,
        slug=store.startup_slug,
        error_message=error_message[:1000],
        status=status,
    )
    db.insert_analysis_error(
        job_id,
        message=error_message[:1000],
        stage="specter_batch_worker",
        error_type="WorkerSubprocessError",
        company_slug=store.startup_slug,
    )
    db.persist_company_failure_result(
        job_id_legacy=job_id,
        result_row={
            "slug": store.startup_slug,
            "company": company,
            "company_name": company.name,
            "evidence_store": store,
            "final_state": {
                "final_arguments": [],
                "final_decision": status,
                "ranking_result": None,
                "all_qa_pairs": [],
            },
            "analysis_status": status,
            "error": error_message[:1000],
            "skipped": False,
        },
        company_payload=payload,
        run_config=run_config,
        versions=versions,
    )


async def _run_company_subprocess(
    *,
    job_id: str,
    work_dir: Path,
    companies_csv: Path,
    people_csv: Path | None,
    company_descriptor: dict[str, Any],
    absolute_index: int,
    total_companies: int,
    run_config: dict[str, Any],
    versions: dict[str, Any],
    use_web_search: bool,
    vc_investment_strategy: str | None,
    worker_id: str,
    completed_companies: int,
    failed_companies: int,
) -> tuple[int, int]:
    company_name = str(company_descriptor.get("name") or company_descriptor.get("slug") or "company")
    prefix = f"Worker evaluating {company_name} ({absolute_index}/{total_companies})"
    db.insert_analysis_event(job_id, message=f"{prefix} — starting", event_type="worker_company", stage="company")
    db.heartbeat_specter_worker_job(
        job_id,
        status="running",
        progress=f"{prefix} — starting",
        active_company_slug=company_descriptor.get("slug"),
        active_company_index=absolute_index,
        completed_companies=completed_companies,
        failed_companies=failed_companies,
        total_companies=total_companies,
        worker_id=worker_id,
    )

    config_path = _write_worker_config(
        work_dir,
        job_id=job_id,
        absolute_index=absolute_index,
        run_config=run_config,
        versions=versions,
    )
    cmd = [
        sys.executable,
        "-m",
        "agent.specter_company_worker",
        "--job-id",
        job_id,
        "--specter-companies",
        str(companies_csv),
        "--company-index",
        str(int(company_descriptor["index"])),
        "--absolute-index",
        str(absolute_index),
        "--config-path",
        str(config_path),
    ]
    if people_csv:
        cmd.extend(["--specter-people", str(people_csv)])
    if use_web_search:
        cmd.append("--use-web-search")
    if vc_investment_strategy:
        cmd.extend(["--vc-investment-strategy", vc_investment_strategy])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    saw_completion_event = False
    company_failed = False
    try:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            if text.startswith(EVENT_PREFIX):
                try:
                    event = json.loads(text[len(EVENT_PREFIX):])
                except Exception:
                    db.insert_analysis_event(job_id, message=text, event_type="worker_stdout", stage="company")
                    continue
                event_type = str(event.get("type") or "").strip().lower()
                if event_type == "progress":
                    message = str(event.get("message") or "").strip()
                    if message:
                        full_message = f"{prefix} — {message}"
                        db.insert_analysis_event(job_id, message=full_message, event_type="progress", stage="company")
                        db.heartbeat_specter_worker_job(
                            job_id,
                            status="running",
                            progress=full_message,
                            active_company_slug=company_descriptor.get("slug"),
                            active_company_index=absolute_index,
                            completed_companies=completed_companies,
                            failed_companies=failed_companies,
                            total_companies=total_companies,
                            worker_id=worker_id,
                        )
                elif event_type == "company_complete":
                    saw_completion_event = True
                    status = str(event.get("status") or "done").strip().lower()
                    if status in {"error", "timeout"}:
                        company_failed = True
                        failed_companies += 1
                        message = f"{prefix} — {status}: {str(event.get('error') or '').strip()}"
                    else:
                        completed_companies += 1
                        message = f"Partial results updated — {completed_companies}/{total_companies} companies completed."
                    db.insert_analysis_event(job_id, message=message, event_type="company_complete", stage="company", payload=event)
                    db.heartbeat_specter_worker_job(
                        job_id,
                        status="running",
                        progress=message,
                        active_company_slug=company_descriptor.get("slug"),
                        active_company_index=absolute_index,
                        completed_companies=completed_companies,
                        failed_companies=failed_companies,
                        total_companies=total_companies,
                        worker_id=worker_id,
                    )
                continue
            db.insert_analysis_event(job_id, message=text, event_type="worker_stdout", stage="company")

        return_code = await process.wait()
        if return_code != 0 and not saw_completion_event:
            error_message = (
                f"Specter company worker exited with code {return_code} "
                f"for company {absolute_index}/{total_companies}."
            )
            _persist_subprocess_failure(
                job_id,
                companies_csv=companies_csv,
                people_csv=people_csv,
                company_index=int(company_descriptor["index"]),
                run_config=run_config,
                versions=versions,
                error_message=error_message,
            )
            failed_companies += 1
            db.insert_analysis_event(job_id, message=f"{prefix} — error: {error_message}", event_type="company_complete", stage="company")
            db.heartbeat_specter_worker_job(
                job_id,
                status="running",
                progress=f"{prefix} — error: {error_message}",
                active_company_slug=company_descriptor.get("slug"),
                active_company_index=absolute_index,
                completed_companies=completed_companies,
                failed_companies=failed_companies,
                total_companies=total_companies,
                worker_id=worker_id,
            )
        return completed_companies, failed_companies
    finally:
        with contextlib.suppress(Exception):
            config_path.unlink()


async def _process_job(job: dict[str, Any], worker_id: str) -> None:
    job_id = str(job.get("job_id") or "")
    if not job_id:
        return

    run_config = dict(job.get("run_config") or {})
    versions = {
        "app_version": run_config.get("app_version"),
        "prompt_version": run_config.get("prompt_version"),
        "pipeline_version": run_config.get("pipeline_version"),
        "schema_version": run_config.get("schema_version"),
    }
    use_web_search = bool(run_config.get("use_web_search"))
    vc_investment_strategy = run_config.get("vc_investment_strategy")

    work_dir: Path | None = None
    try:
        work_dir, companies_csv, people_csv = _download_worker_inputs(job_id, run_config)
        descriptors = list_specter_companies(companies_csv)
        max_startups = web_app._parse_max_startups_from_instructions(run_config.get("instructions"))
        if max_startups is not None:
            descriptors = descriptors[:max_startups]

        completed_keys, completed_companies, failed_companies = _load_completed_company_keys(job_id)
        total_companies = len(descriptors)
        if total_companies <= 0:
            raise RuntimeError("No companies found in Specter data.")

        if completed_keys:
            message = f"Resuming worker batch — {len(completed_keys)}/{total_companies} companies already persisted."
            db.insert_analysis_event(job_id, message=message, event_type="worker_resume", stage="resume")
            db.heartbeat_specter_worker_job(
                job_id,
                status="running",
                progress=message,
                completed_companies=completed_companies,
                failed_companies=failed_companies,
                total_companies=total_companies,
                worker_id=worker_id,
            )

        for absolute_index, descriptor in enumerate(descriptors, start=1):
            company_key = _normalize_company_key(descriptor.get("name"), descriptor.get("slug"))
            if company_key in completed_keys:
                continue
            completed_companies, failed_companies = await _run_company_subprocess(
                job_id=job_id,
                work_dir=work_dir,
                companies_csv=companies_csv,
                people_csv=people_csv,
                company_descriptor=descriptor,
                absolute_index=absolute_index,
                total_companies=total_companies,
                run_config=run_config,
                versions=versions,
                use_web_search=use_web_search,
                vc_investment_strategy=vc_investment_strategy,
                worker_id=worker_id,
                completed_companies=completed_companies,
                failed_companies=failed_companies,
            )
            completed_keys.add(company_key)
            gc.collect()

        db.insert_analysis_event(job_id, message="Finalizing batch results...", event_type="worker_finalizing", stage="finalize")
        db.heartbeat_specter_worker_job(
            job_id,
            status="finalizing",
            progress="Finalizing batch results...",
            completed_companies=completed_companies,
            failed_companies=failed_companies,
            total_companies=total_companies,
            worker_id=worker_id,
        )
        loaded = db.load_job_results(job_id, preferred_mode="specter")
        if not loaded or not isinstance(loaded.get("results"), dict):
            raise RuntimeError("Could not reconstruct final Specter results from persisted state.")
        results = loaded["results"]
        results["job_status"] = "done"
        results["job_message"] = f"Analysis complete — {completed_companies}/{total_companies} companies ranked"
        if "run_costs" not in results:
            run_costs = db.load_run_costs(job_id)
            if isinstance(run_costs, dict):
                results["run_costs"] = run_costs

        if not db.persist_analysis_snapshot(
            job_id,
            results_payload=results,
            run_config=run_config,
            versions=versions,
            worker_state={
                "status": "done",
                "progress": results["job_message"],
                "completed_companies": completed_companies,
                "failed_companies": failed_companies,
                "total_companies": total_companies,
                "worker_service_enabled": True,
            },
        ):
            raise RuntimeError("Could not persist final worker-backed analysis snapshot.")

        db.finish_specter_worker_job(
            job_id,
            status="done",
            progress=results["job_message"],
            completed_companies=completed_companies,
            failed_companies=failed_companies,
            total_companies=total_companies,
        )
        db.insert_analysis_event(job_id, message="Finalizing complete.", event_type="worker_done", stage="finalize")
    except Exception as exc:
        traceback.print_exc()
        message = str(exc)[:1000]
        db.insert_analysis_error(job_id, message=message, stage="specter_batch_worker", error_type=type(exc).__name__)
        db.finish_specter_worker_job(job_id, status="error", progress=message)
        db.insert_analysis_event(job_id, message=f"Worker error: {message}", event_type="worker_error", stage="error")
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        web_app._results_cache.pop(job_id, None)
        gc.collect()


async def _worker_loop(run_once: bool = False) -> None:
    worker_id = _worker_id()
    while True:
        claimed = False
        for candidate in db.list_claimable_specter_worker_jobs(limit=5):
            job = db.claim_specter_worker_job(str(candidate.get("job_id") or ""), worker_id=worker_id)
            if not job:
                continue
            claimed = True
            await _process_job(job, worker_id)
            break
        if run_once:
            return
        if not claimed:
            await asyncio.sleep(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    if not db.is_configured():
        print("Supabase is not configured; Specter worker cannot start.", file=sys.stderr)
        return 1
    asyncio.run(_worker_loop(run_once=args.run_once))
    return 0


if __name__ == "__main__":
    sys.exit(main())
