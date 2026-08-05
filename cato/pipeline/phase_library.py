from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .models import EmpireRun, PhasePromptBundle, PhaseRequirement, PhaseSpec

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_ONE_SHOT_ROOT = Path.home() / "Desktop" / "One Shot Pipeline"
_ONE_SHOT_SCRIPTS = _ONE_SHOT_ROOT / "Scripts"
_CLAUDE_SKILLS_ROOT = Path.home() / ".claude" / "skills"
_CLAUDE_PROMPTS = Path.home() / ".claude" / "Prompts"
_RALPH_SKILL = _CLAUDE_SKILLS_ROOT / "ralph-wiggum-loop" / "SKILL.md"
_PIPELINE_SKILL = _CLAUDE_SKILLS_ROOT / "one-shot-pipeline" / "SKILL.md"


def _read_text(path: Path, *, max_chars: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _snippet(path: Path, *, max_chars: int = 2000) -> str:
    text = _read_text(path, max_chars=max_chars)
    if not text:
        return f"[Missing: {path}]"
    return text


class EmpirePhaseLibrary:
    def __init__(self) -> None:
        self._specs = self._build_specs()

    def spec_for(self, phase: int) -> PhaseSpec:
        try:
            return self._specs[phase]
        except KeyError as exc:
            raise ValueError(f"Unknown phase: {phase}") from exc

    def build_prompt(self, run: EmpireRun, phase: int) -> PhasePromptBundle:
        spec = self.spec_for(phase)
        method = getattr(self, f"_phase_{phase}_bundle")
        return method(run, spec)

    def _build_specs(self) -> dict[int, PhaseSpec]:
        return {
            1: PhaseSpec(
                phase=1,
                name="Market Research",
                worker="claude",
                model_tier="escalation",
                output_dir=".",
                prompt_sources=[
                    _ONE_SHOT_ROOT / "Phases" / "Phase 1-Market research" / "Phase 1 ideation.md",
                    _ONE_SHOT_ROOT / "Phases" / "Phase 1-Market research" / "phase 1 market-research.md",
                ],
                required_outputs=[
                    "phase1_discovery.yaml",
                    "MARKET_RESEARCH.json",
                    "WINNER_SPEC.md",
                ],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "1",
                            "--agent", "deep-research-agent",
                            "--score", "95",
                            "--deliverables",
                            "phase1_discovery.yaml",
                            "MARKET_RESEARCH.json",
                            "WINNER_SPEC.md",
                        ],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "pipeline_telemetry.py",
                        args=["--phase", "1", "--business", "{slug}", "--status", "complete"],
                        exit_code_0_required=False,
                    ),
                ],
                summary="Claude Code runs the two-pass research handoff and saves the market outputs.",
            ),
            2: PhaseSpec(
                phase=2,
                name="SEO + Marketing Strategy",
                worker="claude",
                model_tier="escalation",
                output_dir="phase_2_outputs",
                prompt_sources=[_ONE_SHOT_ROOT / "Phases" / "Phase 2-Atlas SEO" / "phase 2-seo prompt.md"],
                support_workers=["atlas-luna"],
                required_outputs=[
                    "SEO_STRATEGY.json",
                    "SOCIAL_CONTENT.json",
                    "CTA_COPY.json",
                    "DIRECTORY_SUBMISSION_COPY.json",
                    "N8N_AUTOMATION_CONTENT.json",
                    "VIDEO_CONTENT.json",
                    "directory_selection.yaml",
                ],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "2",
                            "--agent", "Atlas-Luna",
                            "--score", "95",
                            "--deliverables",
                            "phase_2_outputs/SEO_STRATEGY.json",
                            "phase_2_outputs/SOCIAL_CONTENT.json",
                            "phase_2_outputs/CTA_COPY.json",
                            "phase_2_outputs/DIRECTORY_SUBMISSION_COPY.json",
                            "phase_2_outputs/N8N_AUTOMATION_CONTENT.json",
                            "phase_2_outputs/VIDEO_CONTENT.json",
                            "phase_2_outputs/directory_selection.yaml",
                        ],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "pipeline_telemetry.py",
                        args=["--phase", "2", "--business", "{slug}", "--status", "complete"],
                        exit_code_0_required=False,
                    ),
                ],
                summary="Claude Code hands the SEO pack to Atlas-Luna and writes the 7 deliverables.",
            ),
            3: PhaseSpec(
                phase=3,
                name="Design System + Agent Discovery",
                worker="gemini",
                model_tier="default",
                output_dir="phase_3_outputs",
                prompt_sources=[
                    _ONE_SHOT_ROOT / "Phases" / "Phase 3-Design.brand direction" / "Phase 3 design-uniqueness prompt.md",
                    _ONE_SHOT_ROOT / "Phases" / "Phase 3-Design.brand direction" / "Phase 3 Logo and Hero Prompt.md",
                    _CLAUDE_SKILLS_ROOT / "one-shot-pipeline" / "prompts" / "phase_3_agent_discovery.md",
                ],
                support_workers=["claude"],
                required_outputs=[
                    "DESIGN_SYSTEM.md",
                    "LOGO_SPECS.md",
                    "HERO_SPECS.md",
                    "AGENT_DISCOVERY_SPEC.md",
                ],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "agent_discovery_generator.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "3",
                            "--agent", "gemini-design",
                            "--score", "92",
                            "--deliverables",
                            "phase_3_outputs/DESIGN_SYSTEM.md",
                            "phase_3_outputs/LOGO_SPECS.md",
                            "phase_3_outputs/HERO_SPECS.md",
                            "phase_3_outputs/AGENT_DISCOVERY_SPEC.md",
                        ],
                    ),
                ],
                summary="Gemini creates the brand system; Claude follows with agent-discovery generation.",
            ),
            4: PhaseSpec(
                phase=4,
                name="Technical Specification",
                worker="claude",
                model_tier="escalation",
                output_dir="phase_4_outputs",
                prompt_sources=[_ONE_SHOT_ROOT / "Phases" / "Phase 4- Tech Stack" / "Phase 4 technical-specification prompt.md"],
                support_workers=["codex"],
                required_outputs=[
                    "TECH_STACK.md",
                    "DATABASE_SCHEMA.md",
                    "API_ROUTES.md",
                    "COMPONENT_TREE.md",
                    "BUILD_PLAN.md",
                    "AUTHENTICATION_SPEC.md",
                ],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "env_manager.py",
                        args=["--root-env", str(_ONE_SHOT_ROOT / ".env"), "--website-env", "{website_dir}\\.env", "--services", "stripe,vercel,neon,nextauth,google,github,porkbun,openai,openrouter", "--verbose"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "neon_provisioner.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "secrets_audit.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "4",
                            "--agent", "techie",
                            "--score", "95",
                            "--deliverables",
                            "phase_4_outputs/TECH_STACK.md",
                            "phase_4_outputs/DATABASE_SCHEMA.md",
                            "phase_4_outputs/API_ROUTES.md",
                            "phase_4_outputs/COMPONENT_TREE.md",
                            "phase_4_outputs/BUILD_PLAN.md",
                            "phase_4_outputs/AUTHENTICATION_SPEC.md",
                        ],
                    ),
                ],
                summary="Claude Code writes the build spec and can hand hard backend pieces to Codex.",
            ),
            5: PhaseSpec(
                phase=5,
                name="Construction (Ralph Loop)",
                worker="claude",
                model_tier="escalation",
                output_dir="website",
                prompt_sources=[
                    _ONE_SHOT_ROOT / "Phases" / "Phase 5-ralph Prep.Ralph Loop" / "AGENTS.md Example.md",
                    _RALPH_SKILL,
                ],
                support_workers=["codex"],
                required_outputs=[".ralph", "IMPLEMENTATION_PLAN.md"],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_phase5_checkpoint.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "pipeline_telemetry.py",
                        args=["--phase", "5", "--business", "{slug}", "--status", "complete"],
                        exit_code_0_required=False,
                    ),
                ],
                summary="Claude runs the Ralph loop controller; Ralph drives Codex through chunked implementation.",
            ),
            6: PhaseSpec(
                phase=6,
                name="Comprehensive Test + Fix",
                worker="codex",
                model_tier="escalation",
                output_dir="audit",
                prompt_sources=[
                    _ONE_SHOT_ROOT / "Phases" / "Phase 6-Comprehensive Test + Fix" / "Phase 6 E2E Testing Prompt.md",
                    _CLAUDE_PROMPTS / "Codex Prompt Phase 7.md",
                ],
                support_workers=["claude"],
                required_outputs=["phase6_e2e.yaml", "TEST_REPORT.md"],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "6",
                            "--agent", "codex-testing",
                            "--score", "95",
                            "--deliverables",
                            "audit/phase6_e2e.yaml",
                            "audit/TEST_REPORT.md",
                        ],
                    ),
                ],
                summary="Codex owns the fix loop and writes the test report and passing state.",
            ),
            7: PhaseSpec(
                phase=7,
                name="Final E2E + Deploy",
                worker="claude",
                model_tier="top",
                output_dir="deployment",
                prompt_sources=[_ONE_SHOT_ROOT / "Phases" / "Phase 7-Final E2E + Deploy + Post-Deploy Automation" / "Phase 7 E2E Testing Prompt.md"],
                required_outputs=["phase7_devops_e2e.yaml", "live_url.txt", "phase7_deploy.yaml"],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "vercel_deployer.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "stripe_setup.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "porkbun_manager.py",
                        args=["--business-path", "{business_dir}"],
                        exit_code_0_required=False,
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "post_deploy_validator.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "create_checkpoint.py",
                        args=[
                            "{slug}",
                            "--phase", "7",
                            "--agent", "devops-architect",
                            "--score", "95",
                            "--deliverables",
                            "deployment/phase7_devops_e2e.yaml",
                            "deployment/live_url.txt",
                            "deployment/phase7_deploy.yaml",
                            "post_deploy_validation_results.json",
                        ],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "pipeline_telemetry.py",
                        args=["--phase", "7", "--business", "{slug}", "--status", "complete"],
                        exit_code_0_required=False,
                    ),
                ],
                summary="Claude runs final verification, deploys, validates production, then stops for approval.",
            ),
            8: PhaseSpec(
                phase=8,
                name="Post-Deploy Marketing Automation",
                worker="claude",
                model_tier="escalation",
                output_dir="reports",
                prompt_sources=[_PIPELINE_SKILL],
                required_outputs=["LAUNCH_SEQUENCE.json", "retrospectives"],
                requirements=[
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "cron_deployer.py",
                        args=["--business-name", "{slug}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "revenue_monitor_generator.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "health_check_scheduler.py",
                        args=["--business-path", "{business_dir}"],
                    ),
                    PhaseRequirement(
                        type="MUST_RUN_SCRIPT",
                        script=_ONE_SHOT_SCRIPTS / "retrospective_writer.py",
                        args=["--business-path", "{business_dir}"],
                        exit_code_0_required=False,
                    ),
                ],
                summary="Claude coordinates launch automation, cron workers, and retrospective writing after approval.",
            ),
            9: PhaseSpec(
                phase=9,
                name="Long-Term Health",
                worker="claude",
                model_tier="default",
                output_dir="reports",
                prompt_sources=[_PIPELINE_SKILL],
                required_outputs=["health_report.md"],
                requirements=[],
                summary="Claude reviews revenue and health signals for day-3, day-14, and day-30 follow-ups.",
            ),
        }

    def _render_requirements(self, run: EmpireRun, requirements: list[PhaseRequirement]) -> list[PhaseRequirement]:
        rendered: list[PhaseRequirement] = []
        values = {
            "slug": run.business_slug,
            "business_dir": str(run.business_dir),
            "website_dir": str(run.business_dir / "website"),
        }
        for req in requirements:
            rendered.append(
                PhaseRequirement(
                    type=req.type,
                    script=req.script,
                    args=[arg.format(**values) for arg in req.args],
                    exit_code_0_required=req.exit_code_0_required,
                    note=req.note,
                )
            )
        return rendered

    def _business_context(self, run: EmpireRun) -> str:
        manifest = _read_json(run.business_dir / "manifest.json")
        return "\n".join(
            [
                f"BUSINESS IDEA: {run.idea}",
                f"BUSINESS SLUG: {run.business_slug}",
                f"BUSINESS DIRECTORY: {run.business_dir}",
                f"PIPELINE RUN ID: {run.run_id}",
                f"MANIFEST: {json.dumps(manifest, indent=2) if manifest else '{}'}",
            ]
        )

    def _phase1_context(self, run: EmpireRun) -> str:
        return "\n".join(
            [
                self._business_context(run),
                "OUTPUT FILES:",
                "- phase1_discovery.yaml",
                "- MARKET_RESEARCH.json",
                "- WINNER_SPEC.md",
                "Save all outputs in the business root.",
            ]
        )

    def _phase2_context(self, run: EmpireRun) -> str:
        research = _read_json(run.business_dir / "MARKET_RESEARCH.json")
        discovery = _read_yaml(run.business_dir / "phase1_discovery.yaml")
        winner_spec = _snippet(run.business_dir / "WINNER_SPEC.md")
        top_keywords = []
        keywords = discovery.get("keywords") or research.get("keywords") or []
        for item in keywords[:10]:
            if isinstance(item, dict):
                top_keywords.append(str(item.get("keyword") or item.get("term") or item))
            else:
                top_keywords.append(str(item))
        competitors = discovery.get("competitors") or research.get("competitors") or []
        return "\n".join(
            [
                self._business_context(run),
                "PHASE 1 CONTEXT:",
                winner_spec,
                f"TARGET AUDIENCE: {discovery.get('target_audience', 'TBD')}",
                f"BRAND TONE: {discovery.get('brand_tone', 'professional yet approachable')}",
                f"TOP KEYWORDS: {', '.join(top_keywords) if top_keywords else 'TBD'}",
                f"COMPETITORS: {competitors}",
                "Write all deliverables to phase_2_outputs.",
            ]
        )

    def _phase3_context(self, run: EmpireRun) -> str:
        winner_spec = _snippet(run.business_dir / "WINNER_SPEC.md")
        seo_strategy = _snippet(run.business_dir / "phase_2_outputs" / "SEO_STRATEGY.json")
        return "\n".join(
            [
                self._business_context(run),
                "PHASE 1 WINNER SPEC:",
                winner_spec,
                "PHASE 2 SEO STRATEGY:",
                seo_strategy,
                "Output brand assets and agent-discovery specs into phase_3_outputs.",
            ]
        )

    def _phase4_context(self, run: EmpireRun) -> str:
        design_system = _snippet(run.business_dir / "phase_3_outputs" / "DESIGN_SYSTEM.md")
        winner_spec = _snippet(run.business_dir / "WINNER_SPEC.md")
        return "\n".join(
            [
                self._business_context(run),
                "BUSINESS SPEC:",
                winner_spec,
                "DESIGN SYSTEM:",
                design_system,
                "Create the full technical specification in phase_4_outputs.",
            ]
        )

    def _phase5_context(self, run: EmpireRun) -> str:
        build_plan = _snippet(run.business_dir / "phase_4_outputs" / "BUILD_PLAN.md")
        tech_stack = _snippet(run.business_dir / "phase_4_outputs" / "TECH_STACK.md")
        return "\n".join(
            [
                self._business_context(run),
                "TECH STACK:",
                tech_stack,
                "BUILD PLAN:",
                build_plan,
                f"WORKTREE ROOT: {run.business_dir / 'worktrees'}",
                f"WEBSITE DIR: {run.business_dir / 'website'}",
            ]
        )

    def _phase6_context(self, run: EmpireRun) -> str:
        return "\n".join(
            [
                self._business_context(run),
                f"WEBSITE DIR: {run.business_dir / 'website'}",
                f"AUDIT DIR: {run.business_dir / 'audit'}",
                f"DEPLOYMENT DIR: {run.business_dir / 'deployment'}",
                "Run tests, fix failures, and write the audit outputs.",
            ]
        )

    def _phase7_context(self, run: EmpireRun) -> str:
        live_url = _read_text(run.business_dir / "deployment" / "live_url.txt", max_chars=400).strip()
        test_report = _snippet(run.business_dir / "audit" / "TEST_REPORT.md")
        return "\n".join(
            [
                self._business_context(run),
                f"LIVE PREVIEW URL: {live_url or 'TBD'}",
                "PHASE 6 TEST REPORT:",
                test_report,
                "Deploy, validate, then stop for approval before Phase 8.",
            ]
        )

    def _phase8_context(self, run: EmpireRun) -> str:
        live_url = _read_text(run.business_dir / "deployment" / "live_url.txt", max_chars=400).strip()
        directory_copy = _snippet(run.business_dir / "phase_2_outputs" / "DIRECTORY_SUBMISSION_COPY.json")
        return "\n".join(
            [
                self._business_context(run),
                f"LIVE URL: {live_url or 'TBD'}",
                "DIRECTORY COPY:",
                directory_copy,
                "Assume Ben has already approved Phase 8.",
            ]
        )

    def _phase9_context(self, run: EmpireRun) -> str:
        return "\n".join(
            [
                self._business_context(run),
                "Review day-3, day-14, and day-30 health signals and revenue monitoring artifacts.",
            ]
        )

    def _join_sources(self, spec: PhaseSpec) -> str:
        blocks = []
        for path in spec.prompt_sources:
            blocks.append(f"\n=== SOURCE: {path} ===\n{_snippet(path, max_chars=7000)}")
        return "\n".join(blocks)

    def _bundle(self, run: EmpireRun, spec: PhaseSpec, handoff: str, context: str) -> PhasePromptBundle:
        requirements = self._render_requirements(run, spec.requirements)
        prompt = "\n\n".join(
            [
                f"EMPIRE PHASE {spec.phase}: {spec.name}",
                f"PRIMARY WORKER: {spec.worker}",
                f"MODEL TIER: {spec.model_tier}",
                f"SUPPORT WORKERS: {', '.join(spec.support_workers) if spec.support_workers else 'none'}",
                f"OUTPUT DIRECTORY: {run.business_dir / spec.output_dir}",
                f"SUMMARY: {spec.summary}",
                "HANDOFF RULES:",
                handoff,
                "BUSINESS CONTEXT:",
                context,
                "SOURCE MATERIAL:",
                self._join_sources(spec),
            ]
        )
        return PhasePromptBundle(
            spec=spec,
            prompt=prompt,
            source_files=list(spec.prompt_sources),
            requirements=requirements,
        )

    def _phase_1_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code acting as dispatcher. Invoke the deep-research workflow in two passes. "
            "Use the ideation prompt first, then the market-research prompt. Replace placeholders with the business idea. "
            "Save outputs as phase1_discovery.yaml, MARKET_RESEARCH.json, and WINNER_SPEC.md in the business root."
        )
        return self._bundle(run, spec, handoff, self._phase1_context(run))

    def _phase_2_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code. Do not write the SEO content yourself. Hand off the work to Atlas-Luna, "
            "prepend the business context block, and return the seven deliverables exactly as named."
        )
        return self._bundle(run, spec, handoff, self._phase2_context(run))

    def _phase_3_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Gemini producing the design system, logo direction, hero direction, and uniqueness guidance. "
            "Do not build code. Produce structured brand outputs that Claude can later feed into agent_discovery_generator.py."
        )
        return self._bundle(run, spec, handoff, self._phase3_context(run))

    def _phase_4_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code running the techie-style technical specification. "
            "Write the production build spec, and hand any hard backend architecture questions to Codex only when necessary."
        )
        return self._bundle(run, spec, handoff, self._phase4_context(run))

    def _phase_5_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code acting as Ralph Loop controller. Use the /ralph-wiggum-loop skill behavior, "
            "generate chunk plans from the Phase 4 artifacts, and drive Codex chunk-by-chunk in the website worktree until the MVP is built."
        )
        return self._bundle(run, spec, handoff, self._phase5_context(run))

    def _phase_6_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Codex running the fix loop. Execute the test plan, repair failures, and leave the website in a passing state with updated audit artifacts."
        )
        return self._bundle(run, spec, handoff, self._phase6_context(run))

    def _phase_7_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code in devops-architect mode. Re-run the final checks, deploy the site, run the post-deploy validators, and stop at the approval gate before Phase 8."
        )
        return self._bundle(run, spec, handoff, self._phase7_context(run))

    def _phase_8_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code coordinating the pm-agent style launch sequence. "
            "Deploy cron workers, revenue monitoring, health checks, and retrospective artifacts."
        )
        return self._bundle(run, spec, handoff, self._phase8_context(run))

    def _phase_9_bundle(self, run: EmpireRun, spec: PhaseSpec) -> PhasePromptBundle:
        handoff = (
            "You are Claude Code reviewing long-term health signals. Summarize revenue, traffic, deployment health, and recommended next decisions."
        )
        return self._bundle(run, spec, handoff, self._phase9_context(run))
