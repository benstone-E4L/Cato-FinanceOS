from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import EmpireRun, PhaseSpec

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _has_any_path(base: Path, names: list[str]) -> bool:
    return any((base / name).exists() for name in names)


@dataclass
class PhaseValidationResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_paths: list[str] = field(default_factory=list)


class EmpirePhaseValidator:
    def validate(self, run: EmpireRun, spec: PhaseSpec) -> PhaseValidationResult:
        base_dir = run.business_dir if spec.output_dir == "." else run.business_dir / spec.output_dir
        errors: list[str] = []
        warnings: list[str] = []
        checked_paths: list[str] = []

        for item in spec.required_outputs:
            path = base_dir if item in (".", spec.output_dir) else base_dir / item
            checked_paths.append(str(path))
            if not path.exists():
                errors.append(f"Missing required output: {path}")

        phase_method = getattr(self, f"_phase_{spec.phase}", None)
        if phase_method is not None:
            phase_method(run, spec, errors, warnings)

        return PhaseValidationResult(
            success=not errors,
            errors=errors,
            warnings=warnings,
            checked_paths=checked_paths,
        )

    def _phase_1(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        discovery = _read_yaml(run.business_dir / "phase1_discovery.yaml")
        research = _read_json(run.business_dir / "MARKET_RESEARCH.json")
        winner_spec = _read_text(run.business_dir / "WINNER_SPEC.md")

        for field in ("tam", "sam", "som"):
            value = discovery.get(field, research.get(field))
            if not isinstance(value, (int, float)):
                errors.append(f"Phase 1 missing numeric field: {field}")
        competitors = discovery.get("competitors") or research.get("competitors") or []
        keywords = discovery.get("keywords") or research.get("keywords") or []
        if _count_items(competitors) < 5:
            errors.append("Phase 1 needs at least 5 competitors.")
        if _count_items(keywords) < 30:
            errors.append("Phase 1 needs at least 30 keywords.")
        if len(winner_spec.strip()) < 200:
            errors.append("Phase 1 WINNER_SPEC.md looks too short.")

    def _phase_2(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / spec.output_dir
        seo = _read_json(base / "SEO_STRATEGY.json")
        social = _read_json(base / "SOCIAL_CONTENT.json")
        cta = _read_json(base / "CTA_COPY.json")
        directory = _read_json(base / "DIRECTORY_SUBMISSION_COPY.json")
        automation = _read_json(base / "N8N_AUTOMATION_CONTENT.json")
        video = _read_json(base / "VIDEO_CONTENT.json")
        directory_selection = _read_yaml(base / "directory_selection.yaml")

        if _count_items(seo.get("short_tail_keywords")) < 10:
            errors.append("Phase 2 SEO_STRATEGY.json needs at least 10 short-tail keywords.")
        if _count_items(seo.get("long_tail_keywords")) < 20:
            errors.append("Phase 2 SEO_STRATEGY.json needs at least 20 long-tail keywords.")
        if _count_items(seo.get("content_clusters")) < 5:
            errors.append("Phase 2 SEO_STRATEGY.json needs at least 5 content clusters.")
        for key in ("twitter", "linkedin", "instagram", "reddit", "product_hunt", "dev_to", "hashnode"):
            if key not in social:
                errors.append(f"Phase 2 SOCIAL_CONTENT.json missing key: {key}")
        if _count_items(cta.get("hero_headline")) < 5:
            errors.append("Phase 2 CTA_COPY.json needs 5 hero headlines.")
        if _count_items(directory.get("features_bullets")) < 10:
            errors.append("Phase 2 DIRECTORY_SUBMISSION_COPY.json needs 10 feature bullets.")
        if _count_items(automation.get("blog_post_queue")) < 10:
            errors.append("Phase 2 N8N_AUTOMATION_CONTENT.json needs 10 blog posts.")
        if "video_decision" not in video:
            errors.append("Phase 2 VIDEO_CONTENT.json missing video_decision.")
        directories = directory_selection.get("directories") or []
        if _count_items(directories) < 80:
            errors.append("Phase 2 directory_selection.yaml needs at least 80 directories.")

    def _phase_3(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / spec.output_dir
        for name in ("DESIGN_SYSTEM.md", "LOGO_SPECS.md", "HERO_SPECS.md", "AGENT_DISCOVERY_SPEC.md"):
            if len(_read_text(base / name).strip()) < 120:
                errors.append(f"Phase 3 {name} looks empty.")

    def _phase_4(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / spec.output_dir
        for name in spec.required_outputs:
            if len(_read_text(base / name).strip()) < 200:
                errors.append(f"Phase 4 {name} looks too short.")

    def _phase_5(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        website = run.business_dir / "website"
        has_project_signal = _has_any_path(website, ["package.json", "src", "app", "pages", "components"])
        if not has_project_signal:
            errors.append("Phase 5 website directory does not look like a built app yet.")

        checkpoint = _read_json(run.business_dir / "checkpoints" / "phase_5.json")
        if not checkpoint:
            errors.append("Phase 5 checkpoint phase_5.json is missing or invalid.")
        else:
            if checkpoint.get("verified") is not True:
                errors.append("Phase 5 checkpoint is not verified.")
            details = checkpoint.get("construction_details", {})
            chunks_completed = details.get("chunks_completed")
            if not isinstance(chunks_completed, int) or chunks_completed < 6:
                errors.append("Phase 5 checkpoint does not show all 6 chunks completed.")
            if details.get("all_chunks_passing") is not True:
                errors.append("Phase 5 checkpoint does not confirm all chunks passing.")
            if details.get("source_code_generated") is not True:
                warnings.append("Phase 5 checkpoint does not confirm source code generation.")

        specs_dir = website / "specs"
        expected_chunk_specs = [
            "chunk1-setup.md",
            "chunk2-auth.md",
            "chunk3-core.md",
            "chunk4-ui.md",
            "chunk5-payments.md",
            "chunk6-final.md",
        ]
        missing_specs = [name for name in expected_chunk_specs if not (specs_dir / name).exists()]
        if missing_specs:
            errors.append(f"Phase 5 is missing chunk specs: {', '.join(missing_specs)}")

        package_json = _read_json(website / "package.json")
        scripts = package_json.get("scripts", {}) if package_json else {}
        for script_name in ("build", "test"):
            if script_name not in scripts:
                errors.append(f"Phase 5 package.json is missing '{script_name}' script.")
        if "typecheck" not in scripts and "lint" not in scripts:
            warnings.append("Phase 5 package.json is missing a typecheck or lint script.")

        progress_text = _read_text(website / ".ralph" / "progress.md")
        if len(progress_text.strip()) < 40:
            warnings.append("Phase 5 .ralph/progress.md is missing or very short.")
        if "validated" not in progress_text.lower():
            warnings.append("Phase 5 progress log does not mention validated chunks.")

        source_file_count = 0
        for ext in ("*.ts", "*.tsx", "*.js", "*.jsx"):
            source_file_count += len(list(website.glob(f"src/**/{ext}")))
            source_file_count += len(list(website.glob(f"app/**/{ext}")))
            source_file_count += len(list(website.glob(f"pages/**/{ext}")))
        if source_file_count < 5:
            errors.append("Phase 5 does not contain enough application source files yet.")

        if len(_read_text(website / "IMPLEMENTATION_PLAN.md").strip()) < 100:
            warnings.append("Phase 5 IMPLEMENTATION_PLAN.md is missing or very short.")

    def _phase_6(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / "audit"
        if not _read_yaml(base / "phase6_e2e.yaml"):
            errors.append("Phase 6 phase6_e2e.yaml is missing or invalid.")
        if len(_read_text(base / "TEST_REPORT.md").strip()) < 120:
            errors.append("Phase 6 TEST_REPORT.md looks empty.")

    def _phase_7(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / "deployment"
        live_url = _read_text(base / "live_url.txt").strip()
        if not live_url.startswith(("http://", "https://")):
            errors.append("Phase 7 live_url.txt must contain an http or https URL.")
        devops_e2e = _read_yaml(base / "phase7_devops_e2e.yaml")
        if not devops_e2e:
            errors.append("Phase 7 phase7_devops_e2e.yaml is missing or invalid.")

        deploy_yaml_text = _read_text(base / "phase7_deploy.yaml")
        if len(deploy_yaml_text.strip()) < 20:
            errors.append("Phase 7 phase7_deploy.yaml is missing or too short.")
        else:
            if not re.search(r"deployment_id\s*:\s*['\"]?[\w-]+", deploy_yaml_text):
                warnings.append("Phase 7 deploy artifact does not expose a deployment_id.")
            if live_url and live_url not in deploy_yaml_text and "vercel" not in deploy_yaml_text.lower():
                warnings.append("Phase 7 deploy artifact does not mention the live URL or Vercel URL.")

        validation_results = _read_json(run.business_dir / "post_deploy_validation_results.json")
        if not validation_results:
            errors.append("Phase 7 post_deploy_validation_results.json is missing or invalid.")
            return

        summary = validation_results.get("summary", {})
        total_tests = summary.get("total_tests")
        failed = summary.get("failed", 0)
        errors_count = summary.get("errors", 0)
        if not isinstance(total_tests, int) or total_tests < 6:
            errors.append("Phase 7 validator results show too few tests.")
        if failed:
            errors.append(f"Phase 7 validator reports {failed} failed test(s).")
        if errors_count:
            errors.append(f"Phase 7 validator reports {errors_count} error/timeout test(s).")

        result_rows = validation_results.get("results", [])
        critical_failures = [
            row for row in result_rows
            if row.get("name") != "Link Health Check"
            and row.get("status") in {"fail", "error", "timeout"}
        ]
        if critical_failures:
            names = ", ".join(row.get("name", "unknown") for row in critical_failures[:3])
            errors.append(f"Phase 7 critical checks failed: {names}")

        link_report = validation_results.get("link_health_report") or {}
        health_pct = link_report.get("health_percentage")
        if isinstance(health_pct, (int, float)):
            if health_pct < 95:
                warnings.append(f"Phase 7 link health is only {health_pct}%.")
        elif result_rows:
            warnings.append("Phase 7 validator did not include a link health percentage.")

        rollback = validation_results.get("auto_rollback") or {}
        rollback_status = rollback.get("status", "")
        if rollback_status and rollback_status != "not_needed":
            errors.append(f"Phase 7 auto rollback status is {rollback_status}.")

        blocked_file = _read_json(run.business_dir / ".phase_8_blocked")
        if blocked_file:
            errors.append("Phase 7 left a .phase_8_blocked marker, so Phase 8 must not proceed.")

    def _phase_8(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / "reports"
        launch = _read_json(base / "LAUNCH_SEQUENCE.json")
        retrospectives = base / "retrospectives"
        if not launch:
            warnings.append("Phase 8 LAUNCH_SEQUENCE.json not found.")
        if not retrospectives.exists():
            warnings.append("Phase 8 retrospectives folder not found.")

    def _phase_9(self, run: EmpireRun, spec: PhaseSpec, errors: list[str], warnings: list[str]) -> None:
        base = run.business_dir / "reports"
        if len(_read_text(base / "health_report.md").strip()) < 50:
            warnings.append("Phase 9 health_report.md is missing or very short.")
