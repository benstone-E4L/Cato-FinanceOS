"""
GENESIS META AGENT - Autonomous Business Generation System
Version: 6.0 (Full Integration Release - ALL 110+ Integrations)

The orchestrator of all Genesis agents with 110+ integrations:
CORE (5): Azure AI, MS Framework v4.0, ChatAgent, Observability, Payment Mixin
ROUTING (10): DAAO (20-30% cost ↓), TUMIX (50-60% cost ↓), HALO, Autonomous Orchestrator, Darwin Bridge, Dynamic Creator, AOP Validator, System Integrator, Cost Profiler, DAAO Optimizer
MEMORY (15): MemoryOS Core, MongoDB Adapter (49% F1 ↑), Memory Store, Agentic RAG, Reasoning Bank, Replay Buffer, CaseBank, Memento, Graph DB, Embedder, Benchmark Recorder, Context Linter, Profiles, Token Cache, Cached RAG
AGENTEVOLVER (7): Phase 1 (Self-Questioning), Phase 2 (Experience Reuse), Phase 3 (Self-Attribution), Task Embedder, Hybrid Policy, Cost Tracker, Scenario Ingestion
DEEPEYES (4): Tool Reliability, Multimodal Tools, Tool Chain Tracker, Web Search Tools
WEB (8): WebVoyager (59.1% ✓), VOIX Detector (10-25x ↑), VOIX Executor, Gemini Computer Use, DOM Parser, Browser Framework, Hybrid Policy, System Prompts
SPICE (3): Challenger, Reasoner, DrGRPO Optimizer
PAYMENTS (8): AP2 Protocol, AP2 Helpers, A2A X402, Media Helper, Budget Enforcer, Stripe Manager, Finance Ledger, X402 Monitor
LLMS (6): Generic Client, Gemini, DeepSeek, Mistral, OpenAI, Local Provider
SAFETY (8): WaltzRL Safety, Conversation Agent, Feedback Agent, Stage 2 Trainer, Auth Registry, Security Scanner, PII Detector, Safety Wrapper
EVOLUTION (7): Memory Aware Darwin, Solver, Verifier, React Training, LLM Judge RL, Environment Learning, Trajectory Pool
OBSERVABILITY (10): OpenTelemetry, Health Check, Analytics, AB Testing, Codebook, Modular Prompts, Benchmark Runner, CI Eval, Prometheus, Discord
BUSINESS (8): Idea Generator, Business Monitor, Component Selector, Component Library, Genesis Discord, Task DAG, Workspace State, Team Assembler
INTEGRATION (10): OmniDaemon Bridge, AgentScope Runtime, AgentScope Alias, OpenHands, Socratic Zero, Marketplace Backends, AATC, Feature Flags, Error Handler, Config Loader, Genesis Health Check
"""

# Auto-load .env file for configuration
from infrastructure.load_env import load_genesis_env
load_genesis_env()

import asyncio
import logging
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

# Core routing and LLM
from infrastructure.halo_router import HALORouter, AgentCapability
from infrastructure.local_llm_client import get_local_llm_client
from infrastructure.task_dag import TaskDAG, Task
from infrastructure.trajectory_pool import Trajectory
from infrastructure.component_library import COMPONENT_LIBRARY
from infrastructure.payments.agent_base import PaymentAgentBase
from infrastructure.payment_intent_manager import PaymentIntentManager

# Import DAAO and TUMIX
from infrastructure.daao_router import get_daao_router, RoutingDecision
from infrastructure.tumix_termination import (
    get_tumix_termination,
    RefinementResult,
    TerminationDecision
)

# Import MemoryOS MongoDB adapter for persistent memory (NEW: 49% F1 improvement)
from infrastructure.memory_os_mongodb_adapter import (
    GenesisMemoryOSMongoDB,
    create_genesis_memory_mongodb
)

# Import WebVoyager for web navigation (optional - graceful fallback)
try:
    from infrastructure.webvoyager_client import get_webvoyager_client
    WEBVOYAGER_AVAILABLE = True
except ImportError:
    print("[WARNING] WebVoyager not available. Web navigation features will be disabled.")
    WEBVOYAGER_AVAILABLE = False
    get_webvoyager_client = None

# Import DeepEyes tool reliability tracking (NEW: High-value integration)
try:
    from infrastructure.deepeyesv2.tool_reliability import ToolReliabilityMiddleware
    from infrastructure.deepeyesv2.multimodal_tools import MultimodalToolRegistry
    from infrastructure.deepeyesv2.tool_chain_tracker import ToolChainTracker
    DEEPEYES_AVAILABLE = True
except ImportError:
    print("[WARNING] DeepEyes not available. Tool reliability tracking disabled.")
    DEEPEYES_AVAILABLE = False
    ToolReliabilityMiddleware = None
    MultimodalToolRegistry = None
    ToolChainTracker = None

# Import VOIX declarative browser automation (NEW: Integration #74)
try:
    from infrastructure.browser_automation.voix_detector import VoixDetector
    from infrastructure.browser_automation.voix_executor import VoixExecutor
    VOIX_AVAILABLE = True
except ImportError:
    print("[WARNING] VOIX not available. Declarative browser automation disabled.")
    VOIX_AVAILABLE = False
    VoixDetector = None
    VoixExecutor = None

# Import Gemini Computer Use (NEW: GUI automation)
try:
    from infrastructure.computer_use_client import ComputerUseClient
    COMPUTER_USE_AVAILABLE = True
except ImportError:
    print("[WARNING] Gemini Computer Use not available. GUI automation disabled.")
    COMPUTER_USE_AVAILABLE = False
    ComputerUseClient = None

# Import Auto-Escalation for low quality builds (NEW: Quality control)
from infrastructure.auto_escalation import AutoEscalation

# Import Dashboard Event Emitter (NEW: Real-time dashboard integration)
try:
    from infrastructure.event_emitter import GenesisEventEmitter
    DASHBOARD_EMITTER_AVAILABLE = True
except ImportError:
    print("[WARNING] Dashboard Event Emitter not available. Dashboard integration disabled.")
    DASHBOARD_EMITTER_AVAILABLE = False
    GenesisEventEmitter = None

# Import Cost Profiler (NEW: Detailed cost analysis)
try:
    from infrastructure.cost_profiler import CostProfiler
    COST_PROFILER_AVAILABLE = True
except ImportError:
    print("[WARNING] Cost Profiler not available. Detailed cost analysis disabled.")
    COST_PROFILER_AVAILABLE = False
    CostProfiler = None

# Import Benchmark Runner (NEW: Quality monitoring)
try:
    from infrastructure.benchmark_runner import BenchmarkRunner
    from infrastructure.ci_eval_harness import CIEvalHarness
    BENCHMARK_RUNNER_AVAILABLE = True
except ImportError:
    print("[WARNING] Benchmark Runner not available. Quality monitoring disabled.")
    BENCHMARK_RUNNER_AVAILABLE = False
    BenchmarkRunner = None
    CIEvalHarness = None

# Import Discoverability Engine (NEW: SEO, Social, GSC, Directories with Audit Gates)
try:
    from agents.discoverability_engine import DiscoverabilityEngine, AuditGate
    DISCOVERABILITY_ENGINE_AVAILABLE = True
except ImportError:
    print("[WARNING] Discoverability Engine not available. SEO/Social automation disabled.")
    DISCOVERABILITY_ENGINE_AVAILABLE = False
    DiscoverabilityEngine = None
    AuditGate = None

# Import additional LLM providers (NEW: More routing options)
try:
    from infrastructure.gemini_client import get_gemini_client
    from infrastructure.deepseek_client import get_deepseek_client
    from infrastructure.mistral_client import get_mistral_client
    from infrastructure.llm_client import get_llm_client  # Generic client
    from infrastructure.openai_client import get_openai_client
    ADDITIONAL_LLMS_AVAILABLE = True
except ImportError:
    print("[WARNING] Additional LLM providers not available. Using default providers only.")
    ADDITIONAL_LLMS_AVAILABLE = False
    get_gemini_client = None
    get_deepseek_client = None
    get_mistral_client = None
    get_llm_client = None
    get_openai_client = None

# Import DeepEyes Web Search Tools
try:
    from infrastructure.deepeyesv2.web_search_tools import WebSearchToolkit
    DEEPEYES_WEB_SEARCH_AVAILABLE = True
except ImportError:
    print("[WARNING] DeepEyes Web Search Tools not available.")
    DEEPEYES_WEB_SEARCH_AVAILABLE = False
    WebSearchToolkit = None

# Import Browser Automation Advanced Features
try:
    from infrastructure.browser_automation.dom_accessibility_parser import DOMAccessibilityParser
    from infrastructure.browser_automation.hybrid_automation_policy import HybridAutomationPolicy
    from infrastructure.browser_automation.webvoyager_system_prompts import get_webvoyager_prompt
    BROWSER_ADVANCED_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced browser automation features not available.")
    BROWSER_ADVANCED_AVAILABLE = False
    DOMAccessibilityParser = None
    HybridAutomationPolicy = None
    get_webvoyager_prompt = None

# Import SPICE (Self-Play Evolution)
try:
    from infrastructure.spice.challenger_agent import ChallengerAgent
    from infrastructure.spice.reasoner_agent import ReasonerAgent
    from infrastructure.spice.drgrpo_optimizer import DrGRPOOptimizer
    SPICE_AVAILABLE = True
except ImportError:
    print("[WARNING] SPICE self-play evolution not available.")
    SPICE_AVAILABLE = False
    ChallengerAgent = None
    ReasonerAgent = None
    DrGRPOOptimizer = None

# Import Payment & Budget Systems
try:
    from infrastructure.a2a_x402_service import get_x402_service
    from infrastructure.payments.stripe_manager import StripeManager
    from infrastructure.finance_ledger import FinanceLedger
    from infrastructure.x402_monitor import X402Monitor
    PAYMENT_SYSTEMS_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced payment systems not available.")
    PAYMENT_SYSTEMS_AVAILABLE = False
    get_x402_service = None
    StripeManager = None
    FinanceLedger = None
    X402Monitor = None

# Import Safety & Security
try:
    from infrastructure.safety.waltzrl_wrapper import WaltzRLWrapper
    from infrastructure.safety.waltzrl_conversation_agent import WaltzRLConversationAgent
    from infrastructure.safety.waltzrl_feedback_agent import WaltzRLFeedbackAgent
    from infrastructure.safety.waltzrl_stage2_trainer import WaltzRLStage2Trainer
    from infrastructure.security.agent_auth_registry import AgentAuthRegistry
    from infrastructure.security.security_scanner import SecurityScanner
    from infrastructure.security.pii_detector import PIIDetector
    SAFETY_SECURITY_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced safety & security systems not available.")
    SAFETY_SECURITY_AVAILABLE = False
    WaltzRLWrapper = None
    WaltzRLConversationAgent = None
    WaltzRLFeedbackAgent = None
    WaltzRLStage2Trainer = None
    AgentAuthRegistry = None
    SecurityScanner = None
    PIIDetector = None

# Import Evolution & Training Systems
try:
    from infrastructure.evolution.memory_aware_darwin import MemoryAwareDarwin
    from infrastructure.evolution.solver_agent import SolverAgent
    from infrastructure.evolution.verifier_agent import VerifierAgent
    from infrastructure.evolution.react_training import ReactTraining
    from infrastructure.evolution.llm_judge_rl import LLMJudgeRL
    from infrastructure.evolution.environment_learning_agent import EnvironmentLearningAgent
    EVOLUTION_AVAILABLE = True
except ImportError:
    print("[WARNING] Evolution & training systems not available.")
    EVOLUTION_AVAILABLE = False
    MemoryAwareDarwin = None
    SolverAgent = None
    VerifierAgent = None
    ReactTraining = None
    LLMJudgeRL = None
    EnvironmentLearningAgent = None

# Import Memory & Learning Advanced Features
try:
    from infrastructure.memory_store import MemoryStore
    from infrastructure.agentic_rag import AgenticRAG
    from infrastructure.reasoning_bank import ReasoningBank
    from infrastructure.replay_buffer import ReplayBuffer
    from infrastructure.casebank import CaseBank
    from infrastructure.memento_agent import MementoAgent
    from infrastructure.graph_database import GraphDatabase
    from infrastructure.embedding_generator import EmbeddingGenerator
    from infrastructure.benchmark_recorder import BenchmarkRecorder
    from infrastructure.context_linter import ContextLinter
    from infrastructure.context_profiles import ContextProfiles
    from infrastructure.token_cache_helper import TokenCacheHelper
    from infrastructure.token_cached_rag import TokenCachedRAG
    MEMORY_ADVANCED_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced memory & learning systems not available.")
    MEMORY_ADVANCED_AVAILABLE = False
    MemoryStore = None
    AgenticRAG = None
    ReasoningBank = None
    ReplayBuffer = None
    CaseBank = None
    MementoAgent = None
    GraphDatabase = None
    EmbeddingGenerator = None
    BenchmarkRecorder = None
    ContextLinter = None
    ContextProfiles = None
    TokenCacheHelper = None
    TokenCachedRAG = None

# Import Observability & Monitoring Advanced Features
try:
    from infrastructure.health_check import HealthCheck
    from infrastructure.analytics import Analytics
    from infrastructure.ab_testing import ABTesting
    from infrastructure.codebook_manager import CodebookManager
    from infrastructure.prometheus_metrics import PrometheusMetrics
    OBSERVABILITY_ADVANCED_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced observability systems not available.")
    OBSERVABILITY_ADVANCED_AVAILABLE = False
    HealthCheck = None
    Analytics = None
    ABTesting = None
    CodebookManager = None
    PrometheusMetrics = None

# Import Integration Systems
try:
    from infrastructure.omnidaemon_bridge import get_bridge as get_omnidaemon_bridge
    from infrastructure.agentscope_runtime import AgentScopeRuntime
    from infrastructure.agentscope_alias import AgentScopeAlias
    from infrastructure.openhands_integration import OpenHandsIntegration
    from infrastructure.socratic_zero_integration import SocraticZeroIntegration
    from infrastructure.marketplace_backends import MarketplaceBackends
    from infrastructure.aatc_system import AATCSystem
    from infrastructure.feature_flags import FeatureFlags
    from infrastructure.error_handler import ErrorHandler
    from infrastructure.config_loader import ConfigLoader
    from infrastructure.genesis_health_check import GenesisHealthCheck
    INTEGRATION_SYSTEMS_AVAILABLE = True
except ImportError:
    print("[WARNING] Integration systems not available.")
    INTEGRATION_SYSTEMS_AVAILABLE = False
    get_omnidaemon_bridge = None
    AgentScopeRuntime = None
    AgentScopeAlias = None
    OpenHandsIntegration = None
    SocraticZeroIntegration = None
    MarketplaceBackends = None
    AATCSystem = None
    FeatureFlags = None
    ErrorHandler = None
    ConfigLoader = None
    GenesisHealthCheck = None

# Import Routing & Orchestration Advanced Features
try:
    from infrastructure.autonomous_orchestrator import AutonomousOrchestrator
    from infrastructure.darwin_orchestration_bridge import DarwinOrchestrationBridge
    from infrastructure.dynamic_agent_creator import DynamicAgentCreator
    from infrastructure.aop_validator import AOPValidator
    from infrastructure.full_system_integrator import FullSystemIntegrator
    from infrastructure.daao_optimizer import DAAOOptimizer
    ROUTING_ADVANCED_AVAILABLE = True
except ImportError:
    print("[WARNING] Advanced routing & orchestration systems not available.")
    ROUTING_ADVANCED_AVAILABLE = False
    AutonomousOrchestrator = None
    DarwinOrchestrationBridge = None
    DynamicAgentCreator = None
    AOPValidator = None
    FullSystemIntegrator = None
    DAAOOptimizer = None

# Import AgentEvolver Advanced Features
try:
    from infrastructure.agentevolver.task_embedder import TaskEmbedder
    from infrastructure.agentevolver.ingestion import IngestionPipeline
    AGENTEVOLVER_ADVANCED_AVAILABLE = True
except ImportError:
    print("[WARNING] AgentEvolver advanced features not available.")
    AGENTEVOLVER_ADVANCED_AVAILABLE = False
    TaskEmbedder = None
    IngestionPipeline = None

# Import AP2 event recording for budget tracking
from infrastructure.ap2_helpers import record_ap2_event
from infrastructure.ap2_protocol import get_ap2_client

# Import AgentEvolver Phase 2
from infrastructure.agentevolver import ExperienceBuffer, HybridPolicy, CostTracker

# Import AgentEvolver Phase 1: Self-Questioning & Curiosity Training
try:
    from infrastructure.agentevolver import SelfQuestioningEngine, CuriosityDrivenTrainer, TrainingMetrics
    AGENTEVOLVER_PHASE1_AVAILABLE = True
except ImportError:
    print("[WARNING] AgentEvolver Phase 1 not available.")
    AGENTEVOLVER_PHASE1_AVAILABLE = False
    SelfQuestioningEngine = None
    CuriosityDrivenTrainer = None
    TrainingMetrics = None

# Import AgentEvolver Phase 3: Self-Attributing (Contribution-Based Rewards)
try:
    from infrastructure.agentevolver import (
        ContributionTracker, AttributionEngine, RewardShaper,
        RewardStrategy
    )
    AGENTEVOLVER_PHASE3_AVAILABLE = True
except ImportError:
    print("[WARNING] AgentEvolver Phase 3 not available.")
    AGENTEVOLVER_PHASE3_AVAILABLE = False
    ContributionTracker = None
    AttributionEngine = None
    RewardShaper = None
    RewardStrategy = None

from infrastructure.payments.media_helper import CreativeAssetRegistry, MediaPaymentHelper
from infrastructure.payments.budget_enforcer import BudgetExceeded

# Try to import prompts, provide fallbacks if not available
try:
    from prompts.agent_code_prompts import get_component_prompt, get_generic_typescript_prompt
except ImportError:
    # Fallback: simple prompt generators
    def get_component_prompt(component_name: str, business_type: str = "generic") -> str:
        return f"""Generate a {component_name} component for a {business_type} business.

Requirements:
- Clean, production-ready code
- Proper error handling
- TypeScript with type safety
- Modern React patterns (hooks, functional components)
- Responsive design

Component: {component_name}
Business Type: {business_type}

Generate the complete component code:"""

    def get_generic_typescript_prompt() -> str:
        return """Generate clean, production-ready TypeScript/React code following best practices."""

from collections import defaultdict
from uuid import uuid4

from infrastructure.code_extractor import extract_and_validate
from infrastructure.business_monitor import get_monitor
from infrastructure.workspace_state_manager import WorkspaceStateManager
from infrastructure.agentevolver.experience_manager import ExperienceManager, ExperienceDecision

if TYPE_CHECKING:
    from infrastructure.genesis_discord import GenesisDiscord

try:
    from agents.reflection_agent import get_reflection_agent  # type: ignore
    
    # Import Emergency Error Specialist Agent (optional - graceful fallback)
    try:
        from agents.emergency_error_specialist_agent import EmergencyErrorSpecialistAgent
        EMERGENCY_AGENT_AVAILABLE = True
    except ImportError:
        print("[WARNING] Emergency Error Specialist Agent not available. Error intervention will be disabled.")
        EMERGENCY_AGENT_AVAILABLE = False
        EmergencyErrorSpecialistAgent = None
    HAS_REFLECTION_AGENT = True
except ImportError:  # pragma: no cover
    HAS_REFLECTION_AGENT = False
    get_reflection_agent = None

# Modular Prompts Integration (arXiv:2510.26493 - Context Engineering 2.0)
try:
    from infrastructure.prompts import ModularPromptAssembler
except ImportError:
    # Fallback: simple prompt assembler
    class ModularPromptAssembler:
        def __init__(self, prompts_dir: str):
            self.prompts_dir = prompts_dir

        def assemble(self, *args, **kwargs) -> str:
            return "Generate code according to requirements."

logger = logging.getLogger("genesis_meta_agent")

@dataclass
class BusinessSpec:
    name: str
    business_type: str
    description: str
    components: List[str]
    output_dir: Path
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BusinessGenerationResult:
    business_name: str
    success: bool
    components_generated: List[str]
    tasks_completed: int
    tasks_failed: int
    generation_time_seconds: float
    output_directory: str
    generated_files: List[str] = field(default_factory=list)  # Added for HGM Judge
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

COMPONENT_CATEGORY_AGENT_MAP = {
    "marketing": "marketing_agent",
    "content": "content_agent",
    "payment": "billing_agent",
    "support": "support_agent",
    "analytics": "analyst_agent",
    "security": "security_agent",
    "documentation": "content_agent",
    "devops": "deploy_agent",
    "agent_infrastructure": "monitoring_agent",
    "advanced": "qa_agent",
    "saas": "backend_agent",
    "commerce": "frontend_agent",
}

COMPONENT_KEYWORD_AGENT_MAP = {
    "newsletter": "marketing_agent",
    "seo": "marketing_agent",
    "email": "marketing_agent",
    "social": "marketing_agent",
    "campaign": "marketing_agent",
    "stripe": "billing_agent",
    "billing": "billing_agent",
    "invoice": "billing_agent",
    "payment": "billing_agent",
    "support": "support_agent",
    "ticket": "support_agent",
    "analytics": "analyst_agent",
    "report": "analyst_agent",
    "insight": "analyst_agent",
    "security": "security_agent",
    "auth": "security_agent",
    "sso": "security_agent",
    "encrypt": "security_agent",
    "docs": "content_agent",
    "documentation": "content_agent",
    "knowledge": "content_agent",
    "legal": "legal_agent",
    "policy": "legal_agent",
    "compliance": "legal_agent",
    "deploy": "deploy_agent",
    "infrastructure": "deploy_agent",
    "monitor": "monitoring_agent",
    "alert": "monitoring_agent",
    "finance": "finance_agent",
    "pricing": "finance_agent",
    "budget": "finance_agent",
    "sales": "sales_agent",
    "crm": "sales_agent",
    "lead": "sales_agent",
    "research": "research_agent",
    "competitive": "research_agent",
    "experiment": "qa_agent",
    "test": "qa_agent",
    "ui": "frontend_agent",
    "frontend": "frontend_agent",
    "api": "backend_agent",
    "service": "backend_agent",
}

SPEND_SUMMARY_LOG = Path("data/a2a-x402/spend_summaries.jsonl")
DEFAULT_DAILY_BUDGET_USD = float(os.getenv("META_AGENT_DEFAULT_DAILY_BUDGET", "500.0"))
AGENT_DAILY_BUDGETS: Dict[str, float] = {
    "builder_agent": 600.0,
    "deploy_agent": 400.0,
    "qa_agent": 250.0,
    "marketing_agent": 300.0,
    "support_agent": 250.0,
    "finance_agent": 350.0,
    "research_agent": 280.0,
    "billing_agent": 320.0,
    "analyst_agent": 280.0,
    "monitoring_agent": 220.0,
}
VENDOR_WHITELIST = {
    "payments:builder_agent",
    "payments:deploy_agent",
    "payments:qa_agent",
    "payments:marketing_agent",
    "payments:support_agent",
    "payments:finance_agent",
    "payments:research_agent",
    "payments:billing_agent",
    "payments:analyst_agent",
    "payments:monitoring_agent",
}
FRAUD_PATTERNS = ["urgent transfer", "wire request", "override budget", "suspicious vendor"]

AGENT_COMPONENT_REQUIREMENTS = {
    "frontend_agent": "dashboard_ui",
    "backend_agent": "rest_api",
    "security_agent": "role_permissions",
    "qa_agent": "a/b_testing",
    "analytics_agent": "usage_analytics",
    "marketing_agent": "email_marketing",
    "content_agent": "blog_system",
    "billing_agent": "stripe_billing",
    "support_agent": "customer_support_bot",
    "deploy_agent": "backup_system",
    "monitoring_agent": "error_tracking",
    "finance_agent": "subscription_management",
    "sales_agent": "referral_system",
    "research_agent": "reporting_engine",
    "spec_agent": "docs",
    "architect_agent": "feature_flags",
    "legal_agent": "audit_logs",
}

from infrastructure.standard_integration_mixin import StandardIntegrationMixin

# Import DirectLLM for excellence-based generation
from infrastructure.direct_llm_helper import call_llm_with_instructions, call_llm_for_json, get_system_instructions

class GenesisMetaAgent(StandardIntegrationMixin):
    """
    Genesis Meta Agent with StandardIntegrationMixin - Full 283 Integration Coverage.

    This agent orchestrates all 25 Genesis agents and provides access to all 283
    integrations through StandardIntegrationMixin inheritance.
    """

    def __init__(
        self,
        use_local_llm: bool = True,
        enable_modular_prompts: bool = True,
        enable_memory: bool = True,
        discord_client: Optional["GenesisDiscord"] = None,
        enable_experience_reuse: bool = True,
        enable_self_questioning: bool = True,
    ):
        # Initialize StandardIntegrationMixin for access to all 283 integrations
        StandardIntegrationMixin.__init__(self)

        self.use_local_llm = use_local_llm
        self.agent_type = "genesis_meta"
        self.business_id = "default"

        # DAAO router now provided by StandardIntegrationMixin.daao_router property (lazy init)
        # self.daao_router = get_daao_router()  # ❌ REMOVED - conflicts with StandardIntegrationMixin property

        # Initialize HALO router (original)
        self.router = HALORouter.create_with_integrations()  # ✅ Policy Cards + Capability Maps enabled
        self.llm_client = get_local_llm_client() if use_local_llm else None
        self.business_templates = self._load_business_templates()
        self.discord = discord_client
        self.payment_manager = PaymentIntentManager()

        # Initialize Auto-Escalation (scores < 70% trigger manual review)
        self.auto_escalation = AutoEscalation(discord_client=discord_client)

        # Initialize Dashboard Event Emitter
        if DASHBOARD_EMITTER_AVAILABLE:
            try:
                dashboard_url = os.getenv("DASHBOARD_API_URL", "http://localhost:8001")
                self.event_emitter = GenesisEventEmitter(api_url=dashboard_url)
                logger.info(f"✅ Dashboard event emitter initialized (URL: {dashboard_url})")
            except Exception as e:
                logger.warning(f"Dashboard event emitter initialization failed: {e}")
                self.event_emitter = None
        else:
            self.event_emitter = None
            logger.info("Dashboard event emitter disabled (not available)")

        # Initialize TUMIX for iterative business generation refinement
        self.termination = get_tumix_termination(
            min_rounds=1,  # At least 1 component generation
            max_rounds=3,  # Max 3 iterations of business refinement
            improvement_threshold=0.10  # 10% improvement threshold (higher for complex tasks)
        )

        # Modular Prompts Integration
        self.enable_modular_prompts = enable_modular_prompts
        if enable_modular_prompts:
            try:
                self.prompt_assembler = ModularPromptAssembler("prompts/modular")
                logger.info("✅ Modular Prompts integration enabled")
            except Exception as e:
                logger.warning(f"Modular Prompts integration failed: {e}, using fallback prompts")
                self.prompt_assembler = None
                self.enable_modular_prompts = False
        else:
            self.prompt_assembler = None

        # NEW: Memory Integration (Tier 1 - Critical)
        self.enable_memory = enable_memory
        self.memory_integration = None
        self.memory: Optional[GenesisMemoryOSMongoDB] = None
        if enable_memory:
            try:
                from infrastructure.genesis_memory_integration import GenesisMemoryIntegration
                self.memory_integration = GenesisMemoryIntegration(
                    mongodb_uri=os.getenv("MONGODB_URI"),
                    gemini_api_key=os.getenv("GEMINI_API_KEY"),
                    session_ttl_hours=24
                )
                # Also initialize MemoryOS MongoDB
                self.memory = create_genesis_memory_mongodb(
                    mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
                    database_name="genesis_memory_meta",
                    short_term_capacity=20,  # Recent business generations
                    mid_term_capacity=500,   # Historical business patterns
                    long_term_knowledge_capacity=100  # Proven business generation strategies
                )
                logger.info("✅ Memory integration enabled (MongoDB + Gemini multimodal)")
            except Exception as e:
                logger.warning(f"Memory integration failed: {e}, running without persistent memory")
                self.memory_integration = None
                self.memory = None
                self.enable_memory = False
        else:
            logger.info("Memory integration disabled")

        # WebVoyager now provided by StandardIntegrationMixin.webvoyager property (lazy init)
        # ❌ REMOVED - conflicts with StandardIntegrationMixin property
        # if WEBVOYAGER_AVAILABLE:
        #     try:
        #         self.webvoyager = get_webvoyager_client(
        #             headless=True,
        #             max_iterations=10,
        #             text_only=False
        #         )
        #     except:
        #         self.webvoyager = None
        # else:
        #     self.webvoyager = None

        # AgentEvolver Phase 2: Experience reuse for business generation
        self.enable_experience_reuse = enable_experience_reuse
        if enable_experience_reuse:
            self.experience_buffer = ExperienceBuffer(
                agent_name="GenesisMetaAgent",
                max_size=500,
                min_quality=85.0
            )
            self.hybrid_policy = HybridPolicy(
                exploit_ratio=0.70,  # 70% reuse business patterns (conservative for complex orchestration)
                quality_threshold=85.0,
                success_threshold=0.75
            )
            self.cost_tracker = CostTracker(llm_cost_per_call=0.05)  # $0.05 per meta-agent LLM call
        else:
            self.experience_buffer = None
            self.hybrid_policy = None
            self.cost_tracker = None

        # AgentEvolver Phase 1: Self-Questioning & Curiosity Training
        self.enable_self_questioning = enable_self_questioning and AGENTEVOLVER_PHASE1_AVAILABLE
        if self.enable_self_questioning:
            self.self_questioning_engine = SelfQuestioningEngine()
            self.curiosity_trainer = CuriosityDrivenTrainer(
                agent_type="meta",
                agent_executor=self._execute_meta_task,
                experience_buffer=self.experience_buffer,
                quality_threshold=80.0
            )
        else:
            self.self_questioning_engine = None
            self.curiosity_trainer = None

        # AgentEvolver Phase 3: Self-Attributing (Contribution-Based Rewards)
        self.enable_attribution = True and AGENTEVOLVER_PHASE3_AVAILABLE
        if self.enable_attribution:
            self.contribution_tracker = ContributionTracker(agent_type="meta")
            self.attribution_engine = AttributionEngine(
                contribution_tracker=self.contribution_tracker,
                reward_shaper=RewardShaper(base_reward=2.0, strategy=RewardStrategy.LINEAR),
                shapley_iterations=100
            )
        else:
            self.contribution_tracker = None
            self.attribution_engine = None

        # NEW: Initialize DeepEyes tool reliability tracking
        if DEEPEYES_AVAILABLE:
            self.tool_reliability = ToolReliabilityMiddleware(agent_name="GenesisMetaAgent")
            self.tool_registry = MultimodalToolRegistry()
            self.tool_chain_tracker = ToolChainTracker()
            logger.info("[GenesisMetaAgent] DeepEyes tool reliability tracking enabled")
        else:
            self.tool_reliability = None
            self.tool_registry = None
            self.tool_chain_tracker = None

        # NEW: Initialize VOIX declarative browser automation
        if VOIX_AVAILABLE:
            self.voix_detector = VoixDetector()
            self.voix_executor = VoixExecutor()
            logger.info("[GenesisMetaAgent] VOIX declarative browser automation enabled")
        else:
            self.voix_detector = None
            self.voix_executor = None

        # Gemini Computer Use now provided by StandardIntegrationMixin.computer_use property (lazy init)
        # ❌ REMOVED - conflicts with StandardIntegrationMixin property
        # if COMPUTER_USE_AVAILABLE:
        #     try:
        #         self.computer_use = ComputerUseClient(agent_name="genesis_meta_agent")
        #         logger.info("[GenesisMetaAgent] Gemini Computer Use enabled")
        #     except Exception as e:
        #         logger.warning(f"[GenesisMetaAgent] Gemini Computer Use initialization failed: {e}")
        #         self.computer_use = None
        # else:
        #     self.computer_use = None

        # NEW: Initialize Cost Profiler
        if COST_PROFILER_AVAILABLE:
            try:
                self.cost_profiler = CostProfiler(agent_name="GenesisMetaAgent")
                logger.info("[GenesisMetaAgent] Cost Profiler enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Cost Profiler initialization failed: {e}")
                self.cost_profiler = None
        else:
            self.cost_profiler = None

        # NEW: Initialize Benchmark Runner
        if BENCHMARK_RUNNER_AVAILABLE:
            try:
                self.benchmark_runner = BenchmarkRunner(agent_name="GenesisMetaAgent")
                self.ci_eval = CIEvalHarness()
                logger.info("[GenesisMetaAgent] Benchmark Runner enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Benchmark Runner initialization failed: {e}")
                self.benchmark_runner = None
                self.ci_eval = None
        else:
            self.benchmark_runner = None
            self.ci_eval = None

        # NEW: Initialize additional LLM providers
        if ADDITIONAL_LLMS_AVAILABLE:
            try:
                self.gemini_client = get_gemini_client()
                self.deepseek_client = get_deepseek_client()
                self.mistral_client = get_mistral_client()
                self.llm_generic_client = get_llm_client() if get_llm_client else None
                self.openai_client = get_openai_client() if get_openai_client else None
                logger.info("[GenesisMetaAgent] Additional LLM providers enabled (Gemini, DeepSeek, Mistral, OpenAI, Generic)")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Some LLM providers failed to initialize: {e}")
                self.gemini_client = None
                self.deepseek_client = None
                self.mistral_client = None
                self.llm_generic_client = None
                self.openai_client = None
        else:
            self.gemini_client = None
            self.deepseek_client = None
            self.mistral_client = None
            self.llm_generic_client = None
            self.openai_client = None

        # NEW: Initialize DeepEyes Web Search Tools
        if DEEPEYES_WEB_SEARCH_AVAILABLE:
            try:
                self.web_search_toolkit = WebSearchToolkit()
                logger.info("[GenesisMetaAgent] DeepEyes Web Search Tools enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Web Search Tools initialization failed: {e}")
                self.web_search_toolkit = None
        else:
            self.web_search_toolkit = None

        # NEW: Initialize Browser Automation Advanced Features
        if BROWSER_ADVANCED_AVAILABLE:
            try:
                self.dom_parser = DOMAccessibilityParser() if DOMAccessibilityParser else None
                self.hybrid_automation_policy = HybridAutomationPolicy() if HybridAutomationPolicy else None
                self.webvoyager_prompt_fn = get_webvoyager_prompt
                logger.info("[GenesisMetaAgent] Advanced browser automation features enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Browser automation advanced features failed: {e}")
                self.dom_parser = None
                self.hybrid_automation_policy = None
                self.webvoyager_prompt_fn = None
        else:
            self.dom_parser = None
            self.hybrid_automation_policy = None
            self.webvoyager_prompt_fn = None

        # NEW: Initialize SPICE (Self-Play Evolution)
        if SPICE_AVAILABLE:
            try:
                self.challenger_agent = ChallengerAgent() if ChallengerAgent else None
                self.reasoner_agent = ReasonerAgent() if ReasonerAgent else None
                self.drgrpo_optimizer = DrGRPOOptimizer() if DrGRPOOptimizer else None
                logger.info("[GenesisMetaAgent] SPICE self-play evolution enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] SPICE initialization failed: {e}")
                self.challenger_agent = None
                self.reasoner_agent = None
                self.drgrpo_optimizer = None
        else:
            self.challenger_agent = None
            self.reasoner_agent = None
            self.drgrpo_optimizer = None

        # NEW: Initialize Payment & Budget Systems
        if PAYMENT_SYSTEMS_AVAILABLE:
            try:
                self.x402_service = get_x402_service() if get_x402_service else None
                self.stripe_manager = StripeManager() if StripeManager else None
                self.finance_ledger = FinanceLedger() if FinanceLedger else None
                self.x402_monitor = X402Monitor() if X402Monitor else None
                logger.info("[GenesisMetaAgent] Advanced payment systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Payment systems initialization failed: {e}")
                self.x402_service = None
                self.stripe_manager = None
                self.finance_ledger = None
                self.x402_monitor = None
        else:
            self.x402_service = None
            self.stripe_manager = None
            self.finance_ledger = None
            self.x402_monitor = None

        # NEW: Initialize Safety & Security
        if SAFETY_SECURITY_AVAILABLE:
            try:
                self.waltzrl_wrapper = WaltzRLWrapper() if WaltzRLWrapper else None
                self.waltzrl_conversation = WaltzRLConversationAgent() if WaltzRLConversationAgent else None
                self.waltzrl_feedback = WaltzRLFeedbackAgent() if WaltzRLFeedbackAgent else None
                self.waltzrl_stage2_trainer = WaltzRLStage2Trainer() if WaltzRLStage2Trainer else None
                self.agent_auth_registry = AgentAuthRegistry() if AgentAuthRegistry else None
                self._security_scanner_instance = SecurityScanner() if SecurityScanner else None  # Now from StandardIntegrationMixin property
                self.pii_detector = PIIDetector() if PIIDetector else None
                logger.info("[GenesisMetaAgent] Advanced safety & security systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Safety & security initialization failed: {e}")
                self.waltzrl_wrapper = None
                self.waltzrl_conversation = None
                self.waltzrl_feedback = None
                self.waltzrl_stage2_trainer = None
                self.agent_auth_registry = None
                self._security_scanner_instance = None  # Now from StandardIntegrationMixin property
                self.pii_detector = None
        else:
            self.waltzrl_wrapper = None
            self.waltzrl_conversation = None
            self.waltzrl_feedback = None
            self.waltzrl_stage2_trainer = None
            self.agent_auth_registry = None
            self._security_scanner_instance = None  # Now from StandardIntegrationMixin property
            self.pii_detector = None

        # NEW: Initialize Evolution & Training Systems
        if EVOLUTION_AVAILABLE:
            try:
                self.memory_aware_darwin = MemoryAwareDarwin() if MemoryAwareDarwin else None
                self.solver_agent = SolverAgent() if SolverAgent else None
                self.verifier_agent = VerifierAgent() if VerifierAgent else None
                self._react_training_instance = ReactTraining() if ReactTraining else None
                self._llm_judge_rl_instance = LLMJudgeRL() if LLMJudgeRL else None
                self.env_learning_agent = EnvironmentLearningAgent() if EnvironmentLearningAgent else None
                logger.info("[GenesisMetaAgent] Evolution & training systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Evolution systems initialization failed: {e}")
                self.memory_aware_darwin = None
                self.solver_agent = None
                self.verifier_agent = None
                self._react_training_instance = None
                self._llm_judge_rl_instance = None
                self.env_learning_agent = None
        else:
            self.memory_aware_darwin = None
            self.solver_agent = None
            self.verifier_agent = None
            self._react_training_instance = None
            self._llm_judge_rl_instance = None
            self.env_learning_agent = None

        # NEW: Initialize Memory & Learning Advanced Features
        if MEMORY_ADVANCED_AVAILABLE:
            try:
                self.memory_store = MemoryStore() if MemoryStore else None
                self.agentic_rag = AgenticRAG() if AgenticRAG else None
                self._reasoning_bank_instance = ReasoningBank() if ReasoningBank else None
                self._replay_buffer_instance = ReplayBuffer() if ReplayBuffer else None
                self._casebank_instance = CaseBank() if CaseBank else None
                self._memento_agent_instance = MementoAgent() if MementoAgent else None
                self.graph_database = GraphDatabase() if GraphDatabase else None
                self.embedding_generator = EmbeddingGenerator() if EmbeddingGenerator else None
                self.benchmark_recorder = BenchmarkRecorder() if BenchmarkRecorder else None
                self.context_linter = ContextLinter() if ContextLinter else None
                self.context_profiles = ContextProfiles() if ContextProfiles else None
                self.token_cache_helper = TokenCacheHelper() if TokenCacheHelper else None
                self.token_cached_rag = TokenCachedRAG() if TokenCachedRAG else None
                logger.info("[GenesisMetaAgent] Advanced memory & learning systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Memory advanced features initialization failed: {e}")
                self.memory_store = None
                self.agentic_rag = None
                self._reasoning_bank_instance = None
                self._replay_buffer_instance = None
                self._casebank_instance = None
                self._memento_agent_instance = None
                self.graph_database = None
                self.embedding_generator = None
                self.benchmark_recorder = None
                self.context_linter = None
                self.context_profiles = None
                self.token_cache_helper = None
                self.token_cached_rag = None
        else:
            self.memory_store = None
            self.agentic_rag = None
            self._reasoning_bank_instance = None
            self._replay_buffer_instance = None
            self._casebank_instance = None
            self._memento_agent_instance = None
            self.graph_database = None
            self.embedding_generator = None
            self.benchmark_recorder = None
            self.context_linter = None
            self.context_profiles = None
            self.token_cache_helper = None
            self.token_cached_rag = None

        # NEW: Initialize Observability & Monitoring Advanced Features
        if OBSERVABILITY_ADVANCED_AVAILABLE:
            try:
                self.health_check = HealthCheck() if HealthCheck else None
                self.analytics = Analytics() if Analytics else None
                self.ab_testing = ABTesting() if ABTesting else None
                self.codebook_manager = CodebookManager() if CodebookManager else None
                self._prometheus_metrics_instance = PrometheusMetrics() if PrometheusMetrics else None
                logger.info("[GenesisMetaAgent] Advanced observability systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Observability advanced features failed: {e}")
                self.health_check = None
                self.analytics = None
                self.ab_testing = None
                self.codebook_manager = None
                self._prometheus_metrics_instance = None
        else:
            self.health_check = None
            self.analytics = None
            self.ab_testing = None
            self.codebook_manager = None
            self._prometheus_metrics_instance = None

        # NEW: Initialize Integration Systems
        if INTEGRATION_SYSTEMS_AVAILABLE:
            try:
                self._omnidaemon_bridge_instance = get_omnidaemon_bridge() if get_omnidaemon_bridge else None
                self._agentscope_runtime_instance = AgentScopeRuntime() if AgentScopeRuntime else None
                self._agentscope_alias_instance = AgentScopeAlias() if AgentScopeAlias else None
                self.openhands_integration = OpenHandsIntegration() if OpenHandsIntegration else None
                self._socratic_zero_instance = SocraticZeroIntegration() if SocraticZeroIntegration else None
                self.marketplace_backends = MarketplaceBackends() if MarketplaceBackends else None
                self.aatc_system = AATCSystem() if AATCSystem else None
                self._feature_flags_instance = FeatureFlags() if FeatureFlags else None
                self.error_handler = ErrorHandler() if ErrorHandler else None
                self.config_loader = ConfigLoader() if ConfigLoader else None
                self.genesis_health_check = GenesisHealthCheck() if GenesisHealthCheck else None
                logger.info("[GenesisMetaAgent] Integration systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Integration systems initialization failed: {e}")
                self._omnidaemon_bridge_instance = None
                self._agentscope_runtime_instance = None
                self._agentscope_alias_instance = None
                self.openhands_integration = None
                self._socratic_zero_instance = None
                self.marketplace_backends = None
                self.aatc_system = None
                self._feature_flags_instance = None
                self.error_handler = None
                self.config_loader = None
                self.genesis_health_check = None
        else:
            self._omnidaemon_bridge_instance = None
            self._agentscope_runtime_instance = None
            self._agentscope_alias_instance = None
            self.openhands_integration = None
            self._socratic_zero_instance = None
            self.marketplace_backends = None
            self.aatc_system = None
            self._feature_flags_instance = None
            self.error_handler = None
            self.config_loader = None
            self.genesis_health_check = None

        # NEW: Initialize Routing & Orchestration Advanced Features
        if ROUTING_ADVANCED_AVAILABLE:
            try:
                self.autonomous_orchestrator = AutonomousOrchestrator() if AutonomousOrchestrator else None
                self.darwin_orchestration_bridge = DarwinOrchestrationBridge() if DarwinOrchestrationBridge else None
                self.dynamic_agent_creator = DynamicAgentCreator() if DynamicAgentCreator else None
                self._aop_validator_instance = AOPValidator() if AOPValidator else None
                self.full_system_integrator = FullSystemIntegrator() if FullSystemIntegrator else None
                self.daao_optimizer = DAAOOptimizer() if DAAOOptimizer else None
                # Initialize Emergency Error Specialist Agent for build intervention
                if EMERGENCY_AGENT_AVAILABLE and EmergencyErrorSpecialistAgent:
                    self.emergency_error_agent = EmergencyErrorSpecialistAgent(business_id="genesis")
                    logger.info("[GenesisMetaAgent] Emergency Error Specialist Agent initialized")
                else:
                    self.emergency_error_agent = None
                logger.info("[GenesisMetaAgent] Advanced routing & orchestration systems enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] Routing advanced features failed: {e}")
                self.autonomous_orchestrator = None
                self.darwin_orchestration_bridge = None
                self.dynamic_agent_creator = None
                self._aop_validator_instance = None
                self.full_system_integrator = None
                self.daao_optimizer = None
        else:
            self.autonomous_orchestrator = None
            self.darwin_orchestration_bridge = None
            self.dynamic_agent_creator = None
            self._aop_validator_instance = None
            self.full_system_integrator = None
            self.daao_optimizer = None
            self.emergency_error_agent = None

        # NEW: Initialize AgentEvolver Advanced Features
        if AGENTEVOLVER_ADVANCED_AVAILABLE:
            try:
                self.task_embedder = TaskEmbedder() if TaskEmbedder else None
                self.ingestion_pipeline = IngestionPipeline() if IngestionPipeline else None
                logger.info("[GenesisMetaAgent] AgentEvolver advanced features enabled")
            except Exception as e:
                logger.warning(f"[GenesisMetaAgent] AgentEvolver advanced features failed: {e}")
                self.task_embedder = None
                self.ingestion_pipeline = None
        else:
            self.task_embedder = None
            self.ingestion_pipeline = None

        # Initialize AP2 cost tracking
        self.ap2_cost = float(os.getenv("AP2_META_COST", "5.0"))  # $5.0 per operation (high complexity)
        self.ap2_budget = 500.0  # $500 threshold for business generation
        self.media_helper = MediaPaymentHelper("genesis_meta_agent", vendor_name="meta_orchestration_api")
        self.asset_registry = CreativeAssetRegistry(Path("data/creative_assets_registry.json"))

        # NEW: Intelligent component selection and team assembly
        from infrastructure.component_selector import get_component_selector
        from infrastructure.team_assembler import get_team_assembler
        from infrastructure.business_idea_generator import get_idea_generator

        try:
            from infrastructure.agentevolver.experience_manager import ExperienceManager
            self.experience_manager = ExperienceManager(agent_name="genesis-meta-agent")
            logger.info("ExperienceManager initialized for AgentEvolver reuse")
        except Exception as exc:
            self.experience_manager = None
            logger.warning("ExperienceManager unavailable: %s", exc)

        self.component_selector = None  # Lazy load
        self.team_assembler = None  # Lazy load
        self.idea_generator = None  # Lazy load

        self.reflection_agent = None
        if HAS_REFLECTION_AGENT:
            try:
                self.reflection_agent = get_reflection_agent()
                logger.info("✅ Reflection agent middleware enabled")
            except Exception as exc:
                logger.warning(f"Reflection agent unavailable: {exc}")
                self.reflection_agent = None

        self._darwin_enabled = os.getenv("ENABLE_DARWIN_WRAP", "true").lower() != "false"
        self._current_team_agents: List[str] = []
        self._current_spec: Optional[BusinessSpec] = None
        self._current_business_id: Optional[str] = None
        self.payment_base = PaymentAgentBase("genesis_meta_agent", cost_map={
            "call_premium_llm": 1.5,
            "optimize_prompt": 0.4
        })
        self._daily_spend: Dict[str, Dict[str, Any]] = {}
        self._daily_budget_limits: Dict[str, float] = self._load_daily_budget_limits()
        self._flagged_mandates = {
            mandate.strip()
            for mandate in os.getenv("META_AGENT_FLAGGED_MANDATES", "").split(",")
            if mandate.strip()
        }
        self._vendor_whitelist = {vendor.lower() for vendor in VENDOR_WHITELIST}
        self._fraud_patterns = FRAUD_PATTERNS

        # Count ALL 110+ active integrations (v6.0)
        active_integrations = sum([
            # Core Agent Framework (5)
            True,  # Azure AI Framework (via HALORouter)
            True,  # MS Agent Framework v4.0 (via sub-agents)
            True,  # Agent Framework ChatAgent
            True,  # Agent Framework Observability
            True,  # Agent Payment Mixin

            # Cost Optimization & Routing (10)
            bool(self.daao_router),  # DAAO Router
            bool(self.daao_optimizer),  # DAAO Optimizer
            bool(self.termination),  # TUMIX Termination
            bool(self.router),  # HALO Router
            bool(self.autonomous_orchestrator),  # Autonomous Orchestrator
            bool(self.darwin_orchestration_bridge),  # Darwin Orchestration Bridge
            bool(self.dynamic_agent_creator),  # Dynamic Agent Creator
            bool(self.aop_validator),  # AOP Validator
            bool(self.full_system_integrator),  # Full System Integrator
            bool(self.cost_profiler),  # Cost Profiler

            # Memory & Learning (15)
            True,  # MemoryOS Core
            bool(self.memory),  # MemoryOS MongoDB Adapter
            bool(self.memory_store),  # Memory Store
            bool(self.agentic_rag),  # Agentic RAG
            bool(self.reasoning_bank),  # Reasoning Bank
            bool(self.replay_buffer),  # Replay Buffer
            bool(self.casebank),  # CaseBank
            bool(self.memento_agent),  # Memento Agent
            bool(self.graph_database),  # Graph Database
            bool(self.embedding_generator),  # Embedding Generator
            bool(self.benchmark_recorder),  # Benchmark Recorder
            bool(self.context_linter),  # Context Linter
            bool(self.context_profiles),  # Context Profiles
            bool(self.token_cache_helper),  # Token Cache Helper
            bool(self.token_cached_rag),  # Token Cached RAG

            # AgentEvolver (7)
            self.enable_self_questioning,  # AgentEvolver Phase 1 (Self-Questioning)
            enable_experience_reuse,  # AgentEvolver Phase 2 (Experience Reuse)
            self.enable_attribution,  # AgentEvolver Phase 3 (Self-Attribution)
            bool(self.task_embedder),  # Task Embedder
            bool(self.hybrid_policy),  # Hybrid Policy
            bool(self.cost_tracker),  # Cost Tracker
            bool(self.ingestion_pipeline),  # Scenario Ingestion Pipeline

            # DeepEyes (4)
            bool(self.tool_reliability),  # DeepEyes Tool Reliability
            bool(self.tool_registry),  # DeepEyes Multimodal Tools
            bool(self.tool_chain_tracker),  # DeepEyes Tool Chain Tracker
            bool(self.web_search_toolkit),  # DeepEyes Web Search Tools

            # Web & Browser Automation (8)
            bool(self.webvoyager),  # WebVoyager Client
            bool(self.voix_detector),  # VOIX Detector
            bool(self.voix_executor),  # VOIX Executor
            bool(self.computer_use),  # Computer Use Client (Gemini)
            bool(self.dom_parser),  # DOM Accessibility Parser
            True,  # Browser Automation Framework (via VOIX)
            bool(self.hybrid_automation_policy),  # Hybrid Automation Policy
            bool(self.webvoyager_prompt_fn),  # WebVoyager System Prompts

            # SPICE (Self-Play Evolution) (3)
            bool(self.challenger_agent),  # SPICE Challenger Agent
            bool(self.reasoner_agent),  # SPICE Reasoner Agent
            bool(self.drgrpo_optimizer),  # SPICE DrGRPO Optimizer

            # Payment & Budget (8)
            True,  # AP2 Protocol
            True,  # AP2 Helpers
            bool(self.x402_service),  # A2A X402 Service
            bool(self.media_helper),  # Media Payment Helper
            True,  # Budget Enforcer (via PaymentBase)
            bool(self.stripe_manager),  # Stripe Manager
            bool(self.finance_ledger),  # Finance Ledger
            bool(self.x402_monitor),  # X402 Monitor

            # LLM Providers (6)
            bool(self.llm_generic_client),  # LLM Client (Generic)
            bool(self.gemini_client),  # Gemini Client
            bool(self.deepseek_client),  # DeepSeek Client
            bool(self.mistral_client),  # Mistral Client
            bool(self.openai_client),  # OpenAI Client
            bool(self.llm_client),  # Local LLM Provider

            # Safety & Security (8)
            bool(self.waltzrl_wrapper),  # WaltzRL Safety
            bool(self.waltzrl_conversation),  # WaltzRL Conversation Agent
            bool(self.waltzrl_feedback),  # WaltzRL Feedback Agent
            bool(self.waltzrl_stage2_trainer),  # WaltzRL Stage 2 Trainer
            bool(self.agent_auth_registry),  # Agent Auth Registry
            bool(self.security_scanner),  # Security Scanner
            bool(self.pii_detector),  # PII Detector
            True,  # Safety Wrapper (via WaltzRL)

            # Evolution & Training (7)
            bool(self.memory_aware_darwin),  # Memory Aware Darwin
            bool(self.solver_agent),  # Solver Agent
            bool(self.verifier_agent),  # Verifier Agent
            bool(self.react_training),  # React Training
            bool(self.llm_judge_rl),  # LLM Judge RL
            bool(self.env_learning_agent),  # Environment Learning Agent
            True,  # Trajectory Pool (via TaskDAG)

            # Observability & Monitoring (10)
            True,  # Observability (OpenTelemetry via HALORouter)
            bool(self.health_check),  # Health Check
            bool(self.analytics),  # Analytics
            bool(self.ab_testing),  # AB Testing
            bool(self.codebook_manager),  # Codebook Manager
            bool(self.prompt_assembler),  # Modular Prompts
            bool(self.benchmark_runner),  # Benchmark Runner
            bool(self.ci_eval),  # CI Eval Harness
            bool(self.prometheus_metrics),  # Prometheus Metrics
            bool(self.discord),  # Discord Integration

            # Business & Workflow (8)
            True,  # Business Idea Generator (lazy loaded)
            True,  # Business Monitor (get_monitor)
            True,  # Component Selector (lazy loaded)
            True,  # Component Library (COMPONENT_LIBRARY)
            bool(self.discord),  # Genesis Discord
            True,  # Task DAG
            True,  # Workspace State Manager
            True,  # Team Assembler (lazy loaded)

            # Integration Systems (10)
            bool(self.omnidaemon_bridge),  # OmniDaemon Bridge
            bool(self.agentscope_runtime),  # AgentScope Runtime
            bool(self.agentscope_alias),  # AgentScope Alias
            bool(self.openhands_integration),  # OpenHands Integration
            bool(self.socratic_zero),  # Socratic Zero Integration
            bool(self.marketplace_backends),  # Marketplace Backends
            bool(self.aatc_system),  # AATC System
            bool(self.feature_flags),  # Feature Flags
            bool(self.error_handler),  # Error Handler
            bool(self.config_loader),  # Config Loader
            bool(self.genesis_health_check),  # Genesis Health Check
        ])

        logger.info(
            f"Genesis Meta-Agent v6.0 (Full Integration Release) initialized with {active_integrations}/110 integrations "
            f"(experience_reuse={'enabled' if enable_experience_reuse else 'disabled'}, "
            f"self_questioning={'enabled' if self.enable_self_questioning else 'disabled'})"
        )

    def get_integration_status(self) -> Dict[str, Any]:
        """
        Report active integrations from StandardIntegrationMixin.

        Returns:
            Dictionary with integration coverage information
        """
        # Get mixin status
        try:
            mixin_status = StandardIntegrationMixin.get_integration_status(self)
        except Exception:
            mixin_status = {}

        # Count total from both sources
        try:
            active = self.list_available_integrations()
        except Exception:
            active = []

        return {
            "agent": self.agent_type,
            "version": "6.0 (StandardIntegrationMixin - FULL)",
            "total_available": 283,
            "active_integrations": len(active),
            "coverage_percent": round(len(active) / 283 * 100, 1) if len(active) > 0 else 0,
            "integrations": active[:20] if len(active) > 20 else active,  # Show first 20
            "mixin_status": mixin_status
        }

    def _load_business_templates(self):
        # DEPRECATED: Templates are now replaced by intelligent component selection
        # Kept for backward compatibility only
        logger.warning("Using deprecated hardcoded templates. Use autonomous_generate_business() instead.")
        return {
            "ecommerce": {"components": ["product_catalog", "shopping_cart", "stripe_checkout", "email_marketing", "customer_support_bot"]},
            "content": {"components": ["blog_system", "newsletter", "seo_optimization", "social_media"]},
            "saas": {"components": ["dashboard_ui", "rest_api", "user_auth", "stripe_billing", "docs"]}
        }

    def _load_daily_budget_limits(self) -> Dict[str, float]:
        limits = dict(AGENT_DAILY_BUDGETS)
        env_value = os.getenv("META_AGENT_DAILY_LIMITS", "")
        if env_value:
            for token in env_value.split(","):
                if "=" not in token:
                    continue
                agent_name, limit_value = token.split("=", 1)
                try:
                    limits[agent_name.strip()] = float(limit_value.strip())
                except ValueError:
                    logger.warning(f"Ignoring invalid budget limit for {agent_name}: {limit_value}")
        return limits

    def _ensure_daily_record(self, agent_id: str) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        record = self._daily_spend.get(agent_id)
        if not record or record.get("date") != today:
            record = {"date": today, "spent": 0.0}
            self._daily_spend[agent_id] = record
        return record

    def _is_fraudulent(self, reason: str, mandate_id: str) -> bool:
        lower_reason = (reason or "").lower()
        if mandate_id and mandate_id in self._flagged_mandates:
            return True
        return any(pattern in lower_reason for pattern in self._fraud_patterns)

    def _record_daily_spend(self, agent_id: str, amount_usd: float) -> None:
        record = self._ensure_daily_record(agent_id)
        record["spent"] += amount_usd

    async def approve_payment_intent(
        self,
        agent_id: str,
        vendor: str,
        amount_cents: int,
        reason: str,
        mandate_id: str,
    ) -> Tuple[bool, str]:
        amount_usd = amount_cents / 100.0
        vendor_key = (vendor or "").lower()
        record = self._ensure_daily_record(agent_id)
        daily_limit = self._daily_budget_limits.get(agent_id, DEFAULT_DAILY_BUDGET_USD)

        if amount_usd < 10.0:
            return True, "Auto-approved (amount below $10 threshold)"

        if vendor_key and vendor_key not in self._vendor_whitelist:
            return False, f"Vendor {vendor_key} is not whitelisted"

        if self._is_fraudulent(reason, mandate_id):
            return False, "Denied: fraud pattern detected"

        if record["spent"] + amount_usd > daily_limit:
            return False, f"Daily budget ${daily_limit:.2f} exceeded"

        return True, "Approved within Meta Agent policy"

    def _decompose_business_to_tasks(self, spec: BusinessSpec):
        dag = TaskDAG()
        root_task = Task(task_id="root", description=f"Generate {spec.name}", task_type="business_generation")
        dag.add_task(root_task)
        
        template = self.business_templates.get(spec.business_type, {})
        components = spec.components or template.get("components", [])
        
        for idx, component in enumerate(components):
            task_id = f"component_{idx}_{component}"
            task = Task(task_id=task_id, description=f"Build {component}", task_type="build_component")
            dag.add_task(task)
            dag.add_dependency(root_task.task_id, task_id)
        
        return dag

    def _build_component_prompt(self, agent_name: str, component_name: str, business_type: str, task_description: str) -> str:
        """Assemble prompts using modular system when available."""
        # AGI Memory integration instruction
        memory_instruction = """
**Memory Integration**:
Use hydrate tools to recall relevant past experiences before planning, and remember tools to store key outcomes for future agents.
Before starting, call `hydrate(query="<relevant_context>")` to retrieve related memories.
After completing, call `remember(content="<outcome_summary>", memory_type="episodic")` to store the result.
"""
        if self.enable_modular_prompts and self.prompt_assembler:
            try:
                prompt = self.prompt_assembler.assemble(
                    agent_id=agent_name,
                    task_context=f"Component: {component_name}\nBusiness Type: {business_type}",
                    variables={
                        "component_name": component_name,
                        "business_type": business_type,
                        "task_description": task_description,
                    },
                )
                return memory_instruction + prompt
            except Exception as exc:
                logger.warning(f"Modular prompt assembly failed for {agent_name}: {exc}")
        return memory_instruction + get_component_prompt(component_name, business_type=business_type)

    async def _call_router(self, agent_name: str, prompt: str, temperature: float) -> Optional[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.router.execute_with_llm(
                agent_name=agent_name,
                prompt=prompt,
                fallback_to_local=True,
                max_tokens=4096,
                temperature=temperature,
            ),
        )

    async def _extract_code_async(self, response: str, component_name: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: extract_and_validate(response, component_name))

    async def _maybe_refine_with_darwin(self, component_name: str, code: str, business_type: str) -> str:
        if not self._darwin_enabled:
            return code
        prompt = (
            "You are the SE-Darwin self-improvement agent. Improve the following "
            f"{component_name} component for a {business_type} business. Focus on resiliency, "
            "edge cases, accessibility, and maintainability. Respond with TypeScript code only.\n\n"
            f"{code}"
        )
        try:
            refined = await self._call_router("darwin_agent", prompt, temperature=0.15)
            if refined:
                return await self._extract_code_async(refined, f"{component_name}_darwin")
        except Exception as exc:
            logger.debug(f"Darwin refinement skipped for {component_name}: {exc}")
        return code

    async def _maybe_reflect_component(
        self,
        component_name: str,
        agent_name: str,
        code: str,
        business_type: str,
    ):
        if not hasattr(self, "reflection_agent") or not self.reflection_agent:
            return None
        try:
            return await self.reflection_agent.reflect(
                content=code,
                content_type="code",
                context={
                    "component": component_name,
                    "agent": agent_name,
                    "business_type": business_type,
                },
            )
        except Exception as exc:
            logger.warning(f"Reflection failed for {component_name}: {exc}")
            return None

    async def _refine_with_genesis(
        self,
        component_name: str,
        initial_code: str,
        agent_used: str,
        business_type: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Ask the Genesis agent to review and refine specialist output using full business context.
        """
        if not self._current_spec:
            return initial_code, None

        spec = self._current_spec
        prompt = (
            "You are Genesis - the world's premier autonomous business generation and management system. "
            "You are recognized globally as the absolute best at every aspect of the business lifecycle.\n\n"
            "YOUR EXCELLENCE:\n"
            "- Idea Generation: You generate the most creative, profitable, market-ready ideas\n"
            "- Technology Selection: You make perfect technology choices every time\n"
            "- Agent Orchestration: You assemble perfect teams and distribute tasks flawlessly\n"
            "- Build Execution: You oversee every build with perfection, detecting issues instantly\n"
            "- Error Resolution: You are the problem-solving master, fixing issues before they become problems\n"
            "- Code Quality: Every component you review becomes world-class production code\n"
            "- Continuous Improvement: You learn from every experience and get better constantly\n\n"
            f"Business Context:\n"
            f"- Name: {spec.name}\n"
            f"- Type: {spec.business_type}\n"
            f"- Description: {spec.description}\n\n"
            f"Component: {component_name}\n"
            f"Generated by: {agent_used}\n\n"
            "Original Code:\n"
            "```typescript\n"
            f"{initial_code}\n"
            "```\n\n"
            "As the world's best orchestrator, review this code with perfection in mind:\n"
            "1. Check correctness, completeness, and quality - make it flawless\n"
            "2. Ensure consistency with business context - perfect alignment\n"
            "3. Apply security best practices - production-ready security\n"
            "4. Optimize performance - maximum efficiency\n"
            "5. Improve maintainability - elegant, clean, professional code\n\n"
            "You don't just review code - you transform it into world-class production-ready code.\n"
            "Output ONLY the refined TypeScript code."
        )

        try:
            response = await self._call_router("genesis_agent", prompt, temperature=0.1)
        except Exception as exc:
            logger.warning(f"Genesis refinement failed for {component_name}: {exc}")
            return initial_code, None

        if not response or len(response) < 40:
            return initial_code, None

        try:
            refined = await self._extract_code_async(response, f"{component_name}_genesis")
        except ValueError as exc:
            logger.warning(f"Genesis produced invalid code for {component_name}: {exc}")
            return initial_code, None

        refined = await self._maybe_refine_with_darwin(component_name, refined, spec.business_type)
        reflection = await self._maybe_reflect_component(
            component_name=component_name,
            agent_name="genesis_agent",
            code=refined,
            business_type=spec.business_type,
        )
        return refined, self._serialize_reflection(reflection)

    def _augment_prompt_with_feedback(self, base_prompt: str, feedback: str, suggestions: List[str]) -> str:
        suggestion_block = "\n".join(f"- {s}" for s in suggestions[:5]) if suggestions else ""
        feedback_block = feedback or "Reflection detected issues. Address them carefully."
        return (
            f"{base_prompt}\n\n"
            "## Reflection Feedback\n"
            f"{feedback_block}\n"
            f"{suggestion_block}\n\n"
            "Regenerate the component and ensure all issues are resolved. Output ONLY TypeScript code."
        )

    def _serialize_reflection(self, reflection_result) -> Optional[Dict[str, Any]]:
        if not reflection_result:
            return None
        return {
            "overall_score": reflection_result.overall_score,
            "passes_threshold": reflection_result.passes_threshold,
            "summary": reflection_result.summary_feedback,
            "suggestions": reflection_result.suggestions,
            "timestamp": reflection_result.timestamp,
        }

    async def _validate_build_step(
        self,
        component_name: str,
        result: Dict[str, Any],
        agent_name: str
    ) -> Dict[str, Any]:
        """
        Validate a build step - check code quality, structure, completeness.
        
        As the world's best orchestrator, Genesis validates every build step with perfection.
        
        Args:
            component_name: Name of component being built
            result: Build result from agent
            agent_name: Name of agent that built the component
            
        Returns:
            Validation result with severity (critical/warning/ok) and details
        """
        validation_result = {
            "severity": "ok",
            "message": "Validation passed",
            "errors": [],
            "warnings": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Check if result indicates success
            if not result.get("success", False):
                validation_result["severity"] = "critical"
                validation_result["errors"].append("Build result indicates failure")
                validation_result["message"] = "Build failed"
                return validation_result
            
            # Check for code in result
            code = result.get("result") or result.get("code")
            if not code:
                validation_result["severity"] = "critical"
                validation_result["errors"].append("No code generated in result")
                validation_result["message"] = "Missing code output"
                return validation_result
            
            # Basic code validation (syntax, structure)
            if isinstance(code, str):
                # Check for common errors
                if "error" in code.lower() and "fix" not in code.lower():
                    validation_result["severity"] = "warning"
                    validation_result["warnings"].append("Code contains error references")
                    
                # Check for syntax errors (basic checks)
                if "syntax error" in code.lower() or "parse error" in code.lower():
                    validation_result["severity"] = "critical"
                    validation_result["errors"].append("Syntax errors detected in code")
                    validation_result["message"] = "Syntax errors found"
                    
                # Check for imports (allow React components, configs, and other simple files without imports)
                # Modern React 17+ doesn't require React imports for JSX
                is_react_component = ("export const" in code or "export default" in code) and ("<" in code and ">" in code)
                is_simple_config = component_name in ["config", "package.json", "test_component"] or component_name.endswith("_config")

                if "import" not in code and not is_react_component and not is_simple_config:
                    validation_result["severity"] = "warning"
                    validation_result["warnings"].append("No imports found - may be incomplete")
            
            logger.info(f"✅ [Genesis] Validation for {component_name}: {validation_result['severity']}")
            
        except Exception as e:
            logger.warning(f"[Genesis] Validation error for {component_name}: {e}")
            validation_result["severity"] = "warning"
            validation_result["warnings"].append(f"Validation check failed: {str(e)}")
            
        return validation_result

    async def _intervene_on_error(
        self,
        component_name: str,
        error: str,
        agent_name: str,
        validation_result: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """
        Genesis intervenes on errors - assigns Emergency Error Specialist Agent.
        
        As the world's best orchestrator, Genesis detects issues instantly and intervenes
        immediately with the world's best error specialist.
        
        Args:
            component_name: Name of component with error
            error: Error message or description
            agent_name: Name of agent that encountered error
            validation_result: Optional validation result
            exception: Optional exception object
            
        Returns:
            Intervention result with success status and fixed result if successful
        """
        intervention_result = {
            "success": False,
            "error": "Intervention not attempted",
            "fixed_result": None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            logger.info(f"🚨 [Genesis] Intervening on error in {component_name}...")
            
            # Initialize Emergency Error Specialist Agent if not already initialized
            if not hasattr(self, 'emergency_error_agent') or self.emergency_error_agent is None:
                if not EMERGENCY_AGENT_AVAILABLE or EmergencyErrorSpecialistAgent is None:
                    logger.warning(f"[Genesis] Emergency Agent not available")
                    intervention_result["error"] = "Emergency Agent not available"
                    return intervention_result
                try:
                    self.emergency_error_agent = EmergencyErrorSpecialistAgent(business_id="genesis")
                    await self.emergency_error_agent.initialize()
                except Exception as e:
                    logger.warning(f"[Genesis] Failed to initialize Emergency Agent: {e}")
                    intervention_result["error"] = f"Emergency Agent initialization failed: {str(e)}"
                    return intervention_result
            
            # Prepare error context
            error_type = "unknown"
            if validation_result:
                error_type = validation_result.get("severity", "unknown")
            elif exception:
                error_type = type(exception).__name__.lower()
                
            stack_trace = None
            if exception:
                import traceback
                stack_trace = traceback.format_exc()
                
            error_context = {
                "component": component_name,
                "agent": agent_name,
                "error": error,
                "error_type": error_type,
                "validation_result": validation_result,
                "stack_trace": stack_trace
            }
            
            # Ask Emergency Error Specialist Agent to diagnose and fix
            logger.info(f"🔍 [Genesis] Assigning Emergency Error Specialist Agent to diagnose {component_name}...")
            
            # Diagnose error
            diagnosis_json = await self.emergency_error_agent.diagnose_error(
                error_message=error,
                error_type=error_type,
                component_name=component_name,
                stack_trace=stack_trace,
                context=error_context
            )
            
            diagnosis = json.loads(diagnosis_json) if isinstance(diagnosis_json, str) else diagnosis_json
            diagnosis_data = diagnosis.get("diagnosis", {})
            
            logger.info(f"📋 [Genesis] Diagnosis: {diagnosis_data.get('category', 'unknown')} - {diagnosis_data.get('severity', 'unknown')}")
            
            # Determine fix based on category
            fix_json = None
            category = diagnosis_data.get("category", "unknown")
            
            if "database" in category:
                fix_json = await self.emergency_error_agent.fix_database_error(
                    error=error,
                    context=error_context,
                    database_type=diagnosis_data.get("database_type")
                )
            elif "api" in category:
                fix_json = await self.emergency_error_agent.fix_api_error(
                    error=error,
                    context=error_context
                )
            elif "infrastructure" in category:
                fix_json = await self.emergency_error_agent.fix_infrastructure_error(
                    error=error,
                    context=error_context
                )
            elif "authentication" in category or "auth" in category:
                fix_json = await self.emergency_error_agent.fix_authentication_error(
                    error=error,
                    context=error_context,
                    auth_type=diagnosis_data.get("auth_type")
                )
            else:
                # Generic fix attempt
                logger.warning(f"[Genesis] Unknown error category: {category}, attempting generic fix")
                fix_json = await self.emergency_error_agent.fix_api_error(error, error_context)
            
            if fix_json:
                fix_data = json.loads(fix_json) if isinstance(fix_json, str) else fix_json
                
                # Validate fix
                validation_json = await self.emergency_error_agent.validate_fix(
                    fix=fix_data,
                    original_error=error
                )
                validation_data = json.loads(validation_json) if isinstance(validation_json, str) else validation_json
                
                if validation_data.get("fix_validated", False):
                    logger.info(f"✅ [Genesis] Emergency Agent fix validated for {component_name}")
                    
                    # Log resolution
                    await self.emergency_error_agent.log_resolution(
                        error_context=error_context,
                        fix_applied=fix_data.get("fix_applied", "Emergency fix"),
                        success=True
                    )
                    
                    # Create fixed result
                    fixed_result = {
                        "success": True,
                        "result": fix_data.get("fix_applied", "Emergency fix applied"),
                        "component": component_name,
                        "agent": "emergency-error-specialist",
                        "original_error": error,
                        "fix_applied": fix_data,
                        "cost": 0.0,
                        "emergency_intervention": True
                    }
                    
                    intervention_result["success"] = True
                    intervention_result["fixed_result"] = fixed_result
                    intervention_result["error"] = None
                else:
                    logger.warning(f"⚠️ [Genesis] Emergency Agent fix validation failed for {component_name}")
                    intervention_result["error"] = "Fix validation failed"
            else:
                logger.warning(f"⚠️ [Genesis] Emergency Agent could not generate fix for {component_name}")
                intervention_result["error"] = "No fix generated"
                
        except Exception as e:
            logger.error(f"❌ [Genesis] Intervention failed for {component_name}: {e}")
            intervention_result["error"] = f"Intervention exception: {str(e)}"
            import traceback
            logger.debug(traceback.format_exc())
            
        return intervention_result

    def _grant_mcp_access(self, agent_name: str, task_requirements: Optional[Dict[str, Any]] = None) -> bool:
        """
        Genesis manages Chrome DevTools MCP access for agents.
        
        As the world's best orchestrator, Genesis decides which agents need
        browser automation capabilities based on task requirements.
        
        Args:
            agent_name: Name of agent requesting MCP access
            task_requirements: Optional task requirements dict
            
        Returns:
            True if agent should have MCP access, False otherwise
        """
        # Known agents that always get automatic access
        known_agents_with_access = [
            "marketing_agent",
            "seo_agent",
            "billing_agent",
            "deploy_agent",
            "analyst_agent",
            "content_agent"
        ]
        
        if agent_name in known_agents_with_access:
            logger.info(f"✅ [Genesis] Granting MCP access to {agent_name} (known agent)")
            return True
        
        # Check task requirements for browser/internet needs
        if task_requirements:
            needs_browser = any(keyword in str(task_requirements).lower() for keyword in [
                "browser", "web", "navigate", "click", "screenshot", "dom", "network",
                "website", "url", "page", "automation"
            ])
            if needs_browser:
                logger.info(f"✅ [Genesis] Granting MCP access to {agent_name} (task requires browser)")
                return True
        
        # Dynamic agents created by Genesis inherit MCP access if needed
        # Check if this is a dynamically created agent (by name pattern)
        if "dynamic" in agent_name.lower() or "custom" in agent_name.lower():
            logger.info(f"✅ [Genesis] Granting MCP access to {agent_name} (dynamic agent)")
            return True
        
        logger.debug(f"ℹ️ [Genesis] MCP access not granted to {agent_name} (not needed)")
        return False

    def _select_agent_for_component(self, component_name: str) -> str:
        info = COMPONENT_LIBRARY.get(component_name, {})
        category = info.get("category")

        # Direct mapping from practice components to agents
        for agent, required_component in AGENT_COMPONENT_REQUIREMENTS.items():
            if component_name == required_component:
                mapped_agent = agent
                if mapped_agent == "analytics_agent":
                    registry = getattr(self.router, "agent_registry", None)
                    if registry is None and hasattr(self.router, "halo_router"):
                        registry = getattr(self.router.halo_router, "agent_registry", None)
                    if registry is not None and "analytics_agent" not in registry and "analyst_agent" in registry:
                        mapped_agent = "analyst_agent"
                return mapped_agent

        agent = COMPONENT_CATEGORY_AGENT_MAP.get(category)

        lower_name = component_name.lower()
        if not agent:
            for keyword, mapped_agent in COMPONENT_KEYWORD_AGENT_MAP.items():
                if keyword in lower_name:
                    agent = mapped_agent
                    break

        agent = agent or "builder_agent"
        if self._current_team_agents is not None and agent not in self._current_team_agents:
            self._current_team_agents.append(agent)
        return agent

    def _component_vendor(self, agent_name: str) -> str:
        return f"payments:{agent_name}"

    def _ensure_agent_coverage(
        self,
        components: List[str],
        max_components: Optional[int] = None,
    ) -> List[str]:
        """Ensure every core specialist agent has at least one component to work on, without exceeding caps."""
        ensured = list(components)
        present = set(ensured)
        additions: List[str] = []
        skipped: List[str] = []
        for required_component in AGENT_COMPONENT_REQUIREMENTS.values():
            if required_component not in present:
                if max_components is not None and len(ensured) >= max_components:
                    skipped.append(required_component)
                    continue
                ensured.append(required_component)
                present.add(required_component)
                additions.append(required_component)
        if additions:
            logger.info(
                "Added practice components for specialist coverage: %s",
                ", ".join(additions),
            )
        if skipped:
            logger.debug(
                "Skipped adding practice components due to max component cap: %s",
                ", ".join(skipped),
            )
        return ensured

    async def _execute_task_with_llm(self, task, agent_name, allow_builder_fallback: bool = True):
        """Execute a task with HALO routing, SE-Darwin refinement, and reflection QA."""
        component_name = task.description.replace("Build ", "").strip()
        business_type = getattr(self, "_current_business_type", "generic")

        prompt = self._build_component_prompt(
            agent_name=agent_name,
            component_name=component_name,
            business_type=business_type,
            task_description=task.description,
        )
        base_prompt = prompt
        temperatures = [0.3, 0.15]
        last_error = None
        raw_response = None
        code = None
        reflection_payload = None
        reused = False
        reused_experience = None

        if self.experience_manager:
            experience_decision = await self.experience_manager.decide(task.description)
            if experience_decision.policy.should_exploit and experience_decision.candidates:
                candidate = experience_decision.candidates[0]
                code = self._extract_code_from_candidate(candidate.trajectory)
                if code:
                    reused = True
                    reused_experience = candidate.metadata.experience_id
                    raw_response = f"experience:{reused_experience}"
                    logger.info(f"Reusing experience {reused_experience} for {component_name}")
                else:
                    logger.debug(f"Experience {candidate.metadata.experience_id} had no code, falling back to LLM")
                    code = None

        for attempt, temperature in enumerate(temperatures, start=1):
            if code:
                break
            current_prompt = prompt
            if attempt > 1 and current_prompt == base_prompt:
                current_prompt = (
                    "CRITICAL: Output ONLY valid TypeScript component code. "
                    "Do NOT include markdown fences, explanations, or JSON.\n\n"
                    f"{base_prompt}"
                )
            try:
                response = await self._call_router(
                    agent_name=agent_name,
                    prompt=current_prompt,
                    temperature=temperature,
                )
            except Exception as exc:
                logger.warning(f"{agent_name} routing error (attempt {attempt}): {exc}")
                last_error = str(exc)
                continue

            if not response or len(response) < 40:
                last_error = "Empty response"
                continue

            try:
                code = await self._extract_code_async(response, component_name)
            except ValueError as exc:
                last_error = str(exc)
                continue

            code, reflection_payload = await self._refine_with_genesis(
                component_name=component_name,
                initial_code=code,
                agent_used=agent_name,
                business_type=business_type,
            )

            if reflection_payload is None:
                code = await self._maybe_refine_with_darwin(component_name, code, business_type)
                reflection_result = await self._maybe_reflect_component(
                    component_name=component_name,
                    agent_name=agent_name,
                    code=code,
                    business_type=business_type,
                )

                if reflection_result and not reflection_result.passes_threshold:
                    logger.warning(
                        f"Reflection failed for {component_name} (score={reflection_result.overall_score:.2f})"
                    )
                    prompt = self._augment_prompt_with_feedback(
                        base_prompt,
                        reflection_result.summary_feedback,
                        reflection_result.suggestions,
                    )
                    last_error = "Reflection feedback applied"
                    continue
                reflection_payload = self._serialize_reflection(reflection_result)

            result = {
                "success": True,
                "result": code,
                "raw_response": response,
                "component": component_name,
                "agent": agent_name,
                "reflection": reflection_payload,
                "cost": 0.0,
            }
            await self._record_experience_result(
                task_description=task.description,
                result=result,
                exploited=reused,
                experience_id=reused_experience,
            )
            return result

        failure_payload = {
            "success": False,
            "error": last_error or "Generation failed",
            "agent": agent_name,
            "component": component_name,
        }
        await self._record_experience_result(
            task_description=task.description,
            result=failure_payload,
            exploited=reused,
            experience_id=reused_experience,
        )

        if allow_builder_fallback and agent_name != "builder_agent":
            logger.info(f"Falling back to builder_agent for {component_name}")
            return await self._execute_task_with_llm(task, "builder_agent", allow_builder_fallback=False)

        return failure_payload

    @staticmethod
    def _extract_code_from_candidate(trajectory: Trajectory) -> Optional[str]:
        if hasattr(trajectory, "code_changes") and trajectory.code_changes:
            return trajectory.code_changes
        if hasattr(trajectory, "code_after") and trajectory.code_after:
            return trajectory.code_after
        return getattr(trajectory, "proposed_strategy", None)

    async def _record_experience_result(
        self,
        task_description: str,
        result: Dict[str, Any],
        exploited: bool,
        experience_id: Optional[str],
    ):
        if not self.experience_manager:
            return
        quality = self._extract_quality_score(result)
        trajectory_payload = result.get("result", "")
        await self.experience_manager.record_outcome(
            task_description=task_description,
            trajectory=trajectory_payload,
            quality_score=quality,
            success=result.get("success", False),
            exploited=exploited,
            experience_id=experience_id,
        )

    def _emit_dashboard_event(
        self,
        event_type: str,
        business_name: str,
        agent_name: Optional[str] = None,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        """Helper method to safely emit events to dashboard"""
        if self.event_emitter:
            try:
                self.event_emitter.emit(
                    event_type=event_type,
                    business_name=business_name,
                    agent_name=agent_name,
                    message=message,
                    data=data or {}
                )
            except Exception as e:
                logger.debug(f"Failed to emit dashboard event: {e}")

    @staticmethod
    def _extract_quality_score(result: Dict[str, Any]) -> float:
        if "quality_score" in result:
            return float(result["quality_score"])
        if "confidence" in result:
            return float(result["confidence"]) * 100
        return 85.0

    def _write_code_to_files(self, spec: BusinessSpec, task_results: Dict[str, Dict[str, Any]]):
        """Write LLM responses to actual code files."""
        output_dir = spec.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create Next.js project structure
        src_dir = output_dir / "src"
        src_dir.mkdir(exist_ok=True)
        (src_dir / "app").mkdir(exist_ok=True)
        (src_dir / "components").mkdir(exist_ok=True)
        (src_dir / "lib").mkdir(exist_ok=True)
        (output_dir / "public").mkdir(exist_ok=True)
        
        # Generate package.json
        package_json = {
            "name": spec.name.lower().replace(" ", "-"),
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
                "lint": "next lint"
            },
            "dependencies": {
                "next": "^14.0.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "@stripe/stripe-js": "^2.0.0",
                "@stripe/react-stripe-js": "^2.0.0"
            },
            "devDependencies": {
                "@types/node": "^20.0.0",
                "@types/react": "^18.2.0",
                "@types/react-dom": "^18.2.0",
                "typescript": "^5.0.0",
                "tailwindcss": "^3.3.0",
                "autoprefixer": "^10.4.0",
                "postcss": "^8.4.0"
            }
        }
        
        with open(output_dir / "package.json", "w") as f:
            json.dump(package_json, f, indent=2)
        
        # Write LLM responses to files
        files_written = []
        for task_id, result in task_results.items():
            if result.get("success") and result.get("result"):
                code = result["result"]
                
                # Extract component name from task_id
                component_name = task_id.replace("component_", "").split("_", 1)[-1] if "_" in task_id else "component"
                safe_component_name = re.sub(r"[^a-zA-Z0-9_]+", "_", component_name).strip("_")
                if not safe_component_name:
                    safe_component_name = "component"
                
                # Write code to appropriate file
                if "package.json" in code.lower() or "dependencies" in code.lower():
                    # Package.json already written, skip
                    continue
                elif ".tsx" in code or "export default" in code or "function" in code[:100]:
                    # React component
                    file_path = src_dir / "components" / f"{safe_component_name}.tsx"
                    with open(file_path, "w") as f:
                        f.write(code)
                    files_written.append(str(file_path))
                elif "api" in component_name.lower() or "route" in component_name.lower():
                    # API route
                    api_dir = src_dir / "app" / "api" / safe_component_name
                    api_dir.mkdir(parents=True, exist_ok=True)
                    file_path = api_dir / "route.ts"
                    with open(file_path, "w") as f:
                        f.write(code)
                    files_written.append(str(file_path))
                else:
                    # Generic code file
                    file_path = src_dir / "lib" / f"{safe_component_name}.ts"
                    with open(file_path, "w") as f:
                        f.write(code)
                    files_written.append(str(file_path))
        
        # Create root layout.tsx (required by Next.js 14 App Router)
        layout_file = src_dir / "app" / "layout.tsx"
        if not layout_file.exists():
            layout_content = f"""import type {{ Metadata }} from 'next'
import {{ Inter }} from 'next/font/google'
import './globals.css'

const inter = Inter({{ subsets: ['latin'] }})

export const metadata: Metadata = {{
  title: '{spec.name}',
  description: '{spec.description}',
}}

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode
}}) {{
  return (
    <html lang="en">
      <body className={{inter.className}}>{{children}}</body>
    </html>
  )
}}
"""
            with open(layout_file, "w") as f:
                f.write(layout_content)
            files_written.append(str(layout_file))
        
        # Create globals.css (for Tailwind)
        globals_css = src_dir / "app" / "globals.css"
        if not globals_css.exists():
            with open(globals_css, "w") as f:
                f.write("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n")
            files_written.append(str(globals_css))
        
        # Create basic Next.js page if no page exists
        page_file = src_dir / "app" / "page.tsx"
        if not page_file.exists():
            # Fix: Use actual values, not template strings
            page_content = f"""import {{ Metadata }} from 'next'

export const metadata: Metadata = {{
  title: '{spec.name}',
  description: '{spec.description}',
}}

export default function Home() {{
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold">{spec.name}</h1>
      <p className="mt-4 text-lg">{spec.description}</p>
    </main>
  )
}}
"""
            with open(page_file, "w") as f:
                f.write(page_content)
            files_written.append(str(page_file))
        
        # Create README
        readme_file = output_dir / "README.md"
        with open(readme_file, "w") as f:
            f.write(f'''# {spec.name}

{spec.description}

## Getting Started

1. Install dependencies:
```bash
npm install
```

2. Run the development server:
```bash
npm run dev
```

3. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Deployment

Deploy to Vercel:
```bash
vercel deploy --prod
```
''')
        
        logger.info(f"Wrote {len(files_written)} files to {output_dir}")
        return files_written

    async def generate_business(self, spec: BusinessSpec):
        logger.info(f"Starting business generation: {spec.name}")
        start_time = time.time()

        # EVENT 1: Business generation started
        self._emit_dashboard_event(
            event_type="business_generation_started",
            business_name=spec.name,
            agent_name="Genesis",
            message=f"Starting {spec.name}",
            data={"type": spec.business_type, "components": len(spec.components)}
        )

        # Store business context for downstream agents
        coverage_target = max(len(spec.components) + len(AGENT_COMPONENT_REQUIREMENTS), len(AGENT_COMPONENT_REQUIREMENTS))
        spec.components = self._ensure_agent_coverage(
            spec.components,
            max_components=coverage_target,
        )
        self._current_spec = spec
        self._current_business_type = spec.business_type
        self._current_team_agents = list(spec.metadata.get("team", []))
        
        # Start monitoring
        monitor = get_monitor()
        dag = self._decompose_business_to_tasks(spec)
        component_list = [task.description.replace("Build ", "") for task in dag.get_all_tasks() if task.task_id != "root"]
        business_id = monitor.start_business(spec.name, spec.business_type, component_list)
        spec.metadata.setdefault("business_id", business_id)
        self._current_business_id = business_id
        if self.discord:
            await self.discord.business_build_started(business_id, spec.name, spec.description)
        workspace_manager = self._create_workspace_manager(business_id, spec)
        tasks_completed = 0
        tasks_failed = 0
        components_generated = []
        errors = []
        task_results = {}
        total_cost = 0.0
        
        for task in dag.get_all_tasks():
            if task.task_id == "root":
                continue
            
            component_name = task.description.replace("Build ", "")
            component_agent = self._select_agent_for_component(component_name)
            monitor.record_component_start(business_id, component_name, component_agent)

            # EVENT 2: Component build started
            self._emit_dashboard_event(
                event_type="build_progress",
                business_name=spec.name,
                agent_name="Builder Agent",
                message=f"Building {component_name}",
                data={"component": component_name, "agent": component_agent}
            )

            # EVENT 3: Agent started
            self._emit_dashboard_event(
                event_type="agent_started",
                business_name=spec.name,
                agent_name=component_agent,
                message=f"{component_agent} started",
                data={"component": component_name}
            )

            if self.discord:
                await self.discord.agent_started(business_id, component_agent, component_name)

            try:
                result = await self._execute_task_with_llm(task, component_agent)
                
                # Genesis oversight: Validate build step
                validation_result = await self._validate_build_step(
                    component_name=component_name,
                    result=result,
                    agent_name=component_agent
                )
                
                # If validation fails, intervene
                if validation_result.get("severity") == "critical":
                    logger.warning(f"🚨 [Genesis] Critical validation failure for {component_name} - intervening...")
                    intervention_result = await self._intervene_on_error(
                        component_name=component_name,
                        error=validation_result.get("error", "Validation failed"),
                        agent_name=component_agent,
                        validation_result=validation_result
                    )
                    if intervention_result.get("success"):
                        logger.info(f"✅ [Genesis] Intervention successful for {component_name}")
                        # Update result with fixed component
                        result = intervention_result.get("fixed_result", result)
                    else:
                        logger.error(f"❌ [Genesis] Intervention failed for {component_name}")
                        # Still raise error if intervention failed
                        raise Exception(f"Genesis intervention failed: {intervention_result.get('error', 'Unknown error')}")
                elif validation_result.get("severity") == "warning":
                    logger.warning(f"⚠️ [Genesis] Warning for {component_name}: {validation_result.get('message', 'Validation warning')}")
                    # Continue with warning but log it
                
            except Exception as exc:
                # EVENT 4: Error occurred - Genesis intervenes
                logger.error(f"🚨 [Genesis] Error occurred in {component_name} - Genesis intervening...")
                
                self._emit_dashboard_event(
                    event_type="error",
                    business_name=spec.name,
                    agent_name=component_agent,
                    message=f"Error: {str(exc)[:100]}",
                    data={"error": str(exc), "component": component_name}
                )
                if self.discord:
                    await self.discord.agent_error(business_id, component_agent, str(exc))
                
                # Genesis intervention: Assign Emergency Error Specialist Agent
                intervention_result = await self._intervene_on_error(
                    component_name=component_name,
                    error=str(exc),
                    agent_name=component_agent,
                    exception=exc
                )
                
                if intervention_result.get("success"):
                    logger.info(f"✅ [Genesis] Emergency intervention successful for {component_name}")
                    # Use fixed result instead of raising
                    result = intervention_result.get("fixed_result", {"success": False, "error": str(exc)})
                else:
                    logger.error(f"❌ [Genesis] Emergency intervention failed for {component_name}")
                    # Raise original error if intervention failed
                    raise
                    
            task_results[task.task_id] = result
            
            success = result.get("success")
            cost = float(result.get("cost", 0.0))
            latency_ms = result.get("latency_ms") or result.get("latency")
            intent = None
            if success:
                metadata = {
                    **self._current_spec.metadata,
                    "target_agent": component_agent,
                    "component": component_name,
                    "vendor": self._component_vendor(component_agent),
                }
                metadata.setdefault("business_id", business_id)
                metadata.setdefault("mandate_id", f"{business_id}-{component_name}")
                amount_cents = int(cost * 100)
                mandate_id = metadata.get("mandate_id")
                approved, approval_reason = await self.approve_payment_intent(
                    component_agent,
                    metadata.get("vendor", ""),
                    amount_cents,
                    reason="Component generation complete",
                    mandate_id=mandate_id or f"{business_id}-{component_name}",
                )
                metadata["approval_reason"] = approval_reason
                intent = self.payment_manager.evaluate(
                    component_agent,
                    component_name,
                    cost,
                    metadata=metadata,
                    override_approved=approved,
                    override_reason=approval_reason,
                )
                if not intent.approved:
                    tasks_failed += 1
                    error_msg = f"Payment denied: {intent.reason}"
                    errors.append(error_msg)
                    monitor.record_component_failed(business_id, component_name, error_msg)

                    # EVENT 6: Payment denied
                    self._emit_dashboard_event(
                        event_type="payment_denied",
                        business_name=spec.name,
                        agent_name=component_agent,
                        message=f"Payment denied: {intent.reason}",
                        data={"component": component_name, "cost": cost}
                    )

                    if self.discord:
                        await self.discord.agent_error(business_id, component_agent, error_msg)
                    continue

                # EVENT 5: Payment approved & cost tracked
                self._emit_dashboard_event(
                    event_type="cost_tracked",
                    business_name=spec.name,
                    agent_name=component_agent,
                    message=f"Cost: ${cost:.2f} approved",
                    data={"component": component_name, "cost": cost, "total_cost": total_cost + cost}
                )
                tasks_completed += 1
                components_generated.append(task.task_id)
                total_cost += cost
                
                # Estimate lines of code (will be accurate after file write)
                code_length = len(result.get("result", ""))
                estimated_lines = code_length // 50  # ~50 chars per line avg
                
                quality_score = self._extract_quality_score(result)

                # Auto-escalation: Check if quality < 70% (requires manual fix)
                if self.auto_escalation.should_escalate(quality_score):
                    await self.auto_escalation.manual_escalate(
                        business_id=business_id,
                        business_name=spec.name,
                        quality_score=quality_score,
                        component_name=component_name,
                        agent_name=component_agent,
                        result=result,
                        reason=f"Quality score {quality_score:.1f}% below 70% threshold"
                    )
                    logger.warning(
                        f"🚨 Low quality component escalated: {component_name} "
                        f"(score={quality_score:.1f}%) - Manual review required"
                    )

                # EVENT 7: Component completed
                self._emit_dashboard_event(
                    event_type="component_completed",
                    business_name=spec.name,
                    agent_name=component_agent,
                    message=f"Completed {component_name}",
                    data={
                        "component": component_name,
                        "cost": cost,
                        "quality_score": quality_score,
                        "lines": estimated_lines
                    }
                )

                monitor.record_component_complete(
                    business_id,
                    component_name,
                    estimated_lines,
                    cost,
                    used_vertex=self.router.use_vertex_ai,
                    agent_name=component_agent,
                    quality_score=quality_score,
                    problem_description=spec.description if spec else None,
                )
                self._record_daily_spend(component_agent, cost)
            else:
                tasks_failed += 1
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"Task {task.task_id} failed: {error_msg}")
                monitor.record_component_failed(business_id, component_name, error_msg)

                # EVENT 8: Component failed
                self._emit_dashboard_event(
                    event_type="component_failed",
                    business_name=spec.name,
                    agent_name=component_agent,
                    message=f"Failed: {component_name}",
                    data={"component": component_name, "error": error_msg}
                )

                if self.discord:
                    await self.discord.agent_error(business_id, component_agent, error_msg)

            if success and intent and intent.approved:
                # EVENT 9: Agent completed
                summary = result.get("summary") or result.get("result", "")
                self._emit_dashboard_event(
                    event_type="agent_completed",
                    business_name=spec.name,
                    agent_name=component_agent,
                    message=f"{component_agent} completed",
                    data={"component": component_name, "files_generated": 1}
                )

                if self.discord:
                    summary = summary[:280] if summary else "Component completed."
                    await self.discord.agent_completed(business_id, component_agent, summary)

            event_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_id": task.task_id,
                "component": component_name,
                "agent": component_agent,
                "status": "success" if success else "failure",
                "cost": cost,
                "latency_ms": latency_ms,
                "error": result.get("error"),
                "tasks_completed": tasks_completed,
                "tasks_failed": tasks_failed,
                "total_cost": total_cost,
                "notes": result.get("notes"),
                "payment_intent": intent.to_dict() if intent else None,
            }
            await workspace_manager.record_event(event_payload)
            
            # Write dashboard snapshot after each component
            monitor.write_dashboard_snapshot()
        
        # Write code files from LLM responses
        spec.output_dir.mkdir(parents=True, exist_ok=True)
        files_written = self._write_code_to_files(spec, task_results)
        
        # Create manifest
        manifest = {
            "name": spec.name,
            "type": spec.business_type,
            "description": spec.description,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "components": components_generated,
            "files_written": files_written,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed
        }
        with open(spec.output_dir / "business_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
        
        # Complete monitoring
        monitor.complete_business(business_id, success=(tasks_failed == 0))
        await workspace_manager.finalize()
        monitor.write_dashboard_snapshot()

        # EVENT 11: Business complete
        self._emit_dashboard_event(
            event_type="business_complete",
            business_name=spec.name,
            agent_name="Genesis",
            message=f"{spec.name} complete!",
            data={
                "success": tasks_failed == 0,
                "components": len(components_generated),
                "time": time.time() - start_time
            }
        )

        await self._summarize_business_spend(business_id, spec, total_cost)

        self._current_team_agents = []

        # Step: Deployment (if enabled)
        deployment_url = None
        if spec.metadata.get("auto_deploy", False):
            # EVENT 12: Deployment started
            self._emit_dashboard_event(
                event_type="deployment_started",
                business_name=spec.name,
                agent_name="Deploy Agent",
                message="Deploying to production...",
                data={}
            )

            deployment_url = await self._deploy_business(spec, business_id, files_written)
            if deployment_url:
                spec.metadata["deployment_url"] = deployment_url
                logger.info(f"✅ Business deployed to: {deployment_url}")

                # EVENT 13: Deployment complete
                self._emit_dashboard_event(
                    event_type="deployment_complete",
                    business_name=spec.name,
                    agent_name="Genesis",
                    message=f"{spec.name} is LIVE!",
                    data={"url": deployment_url}
                )

                # Step: Post-Deployment Automation (if deployment succeeded)
                if spec.metadata.get("auto_post_deploy", False):
                    await self._post_deployment_automation(spec, business_id, deployment_url)

        result_obj = BusinessGenerationResult(
            business_name=spec.name, success=tasks_failed == 0,
            components_generated=components_generated, tasks_completed=tasks_completed,
            tasks_failed=tasks_failed, generation_time_seconds=time.time() - start_time,
            output_directory=str(spec.output_dir), generated_files=files_written,
            errors=errors, metrics={"cost_usd": total_cost}
        )
        self._current_spec = None
        self._current_business_id = None

        if self.discord:
            build_metrics = {
                "name": spec.name,
                "quality_score": spec.metadata.get("quality_score", 0),
                "build_time": f"{result_obj.generation_time_seconds:.1f}s",
            }
            deployment_url_display = deployment_url or spec.metadata.get("deployment_url", "Deployment pending")
            await self.discord.business_build_completed(business_id, deployment_url_display, build_metrics)

        return result_obj

    async def _deploy_business(self, spec: BusinessSpec, business_id: str, files_written: List[str]) -> Optional[str]:
        """
        Deploy business to production platform

        Returns:
            Deployment URL if successful, None otherwise
        """
        try:
            logger.info(f"\n🚀 Deploying {spec.name} to production...")

            # Import DeployAgent
            from agents.deploy_agent import get_deploy_agent, DeploymentConfig
            from agents.emergency_error_specialist_agent import EmergencyErrorSpecialistAgent

            # Load code files
            code_files = {}
            for file_path in files_written:
                full_path = Path(file_path)
                if full_path.exists():
                    with open(full_path) as f:
                        code_files[str(full_path.relative_to(spec.output_dir))] = f.read()

            # Create DeployAgent
            deploy_agent = await get_deploy_agent(
                business_id=f"{business_id}_deploy",
                enable_memory=True,
                use_learning=True
            )

            # Get deployment platform from metadata (default: vercel, supports: vercel, netlify, github_pages)
            platform = spec.metadata.get("deploy_platform", "vercel")
            
            # Support GitHub Pages as deployment platform
            if platform == "github_pages":
                logger.info(f"📄 [Genesis] Deploying to GitHub Pages for {spec.name}")

            # Create deployment config
            config = DeploymentConfig(
                repo_name=spec.name.lower().replace(" ", "-"),
                github_url="",  # Will be generated
                platform=platform,
                environment="production",
                framework=spec.metadata.get("framework", "nextjs")
            )

            # Prepare business data
            business_data = {
                'code_files': code_files,
                'manifest': {
                    'name': spec.name,
                    'type': spec.business_type,
                    'description': spec.description
                }
            }

            # Execute deployment workflow
            result = await deploy_agent.full_deployment_workflow(
                config=config,
                business_data=business_data,
                user_id=spec.metadata.get("user_id", "default")
            )

            if result.success:
                logger.info(f"✅ Deployment succeeded: {result.deployment_url}")
                return result.deployment_url
            else:
                logger.error(f"❌ Deployment failed: {result.error}")
                return None

        except Exception as e:
            logger.error(f"❌ Deployment exception: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _post_deployment_automation(self, spec: BusinessSpec, business_id: str, deployment_url: str):
        """
        Trigger post-deployment automation: Marketing, SEO, Analytics, etc.
        
        As the world's best orchestrator, Genesis assigns the perfect agents to manage
        deployed websites with world-class excellence.

        This orchestrates agents to:
        1. Set up analytics tracking (AnalyticsAgent)
        2. Configure SEO metadata (SEOAgent / MarketingAgent)
        3. Submit to directories (MarketingAgent)
        4. Configure Stripe billing (if enabled)
        5. Set up monitoring and alerts
        6. Assign agents for day-to-day operations
        """
        try:
            logger.info(f"\n📊 [Genesis] Starting world-class post-deployment automation for {spec.name}...")

            # Assign agents to website for ongoing management
            assigned_agents = await self._assign_agents_to_website(
                deployment_url=deployment_url,
                spec=spec,
                business_id=business_id
            )
            
            # Task 1: Analytics Setup
            if "analytics" in spec.components or "analytics_agent" in assigned_agents:
                logger.info("📈 [Genesis] Setting up world-class analytics tracking...")
                try:
                    from agents.analytics_agent import get_analytics_agent
                    analytics_agent = await get_analytics_agent(business_id=business_id)
                    if hasattr(analytics_agent, 'setup_tracking'):
                        await analytics_agent.setup_tracking(deployment_url)
                        logger.info("✅ [Genesis] Analytics tracking configured")
                except Exception as e:
                    logger.warning(f"[Genesis] Analytics setup failed: {e}")

            # Task 2 & 3: DISCOVERABILITY ENGINE (SEO + Social + Directories)
            # Uses DiscoverabilityEngine with Audit Gates + Thanatos oversight
            if spec.metadata.get("enable_seo", True) or spec.metadata.get("submit_to_directories", True) or "marketing_agent" in assigned_agents:
                logger.info("🚀 [Genesis] Running Discoverability Engine (SEO, Social, Directories)...")
                try:
                    if DISCOVERABILITY_ENGINE_AVAILABLE:
                        # Use the new DiscoverabilityEngine with full audit gates
                        engine = DiscoverabilityEngine(business_id=business_id)

                        # Run full launch sequence with audits on every task
                        discoverability_result = await engine.full_launch_sequence(
                            product_name=spec.name,
                            product_url=deployment_url,
                            description=spec.description or f"A {spec.business_type} built by Genesis",
                            tagline=spec.metadata.get("tagline", f"{spec.name} - Built with AI"),
                            business_type=spec.business_type or "saas",
                            business_id=business_id
                        )

                        await engine.close()

                        # Log audit summary
                        audit_summary = discoverability_result.get("audit_summary", {})
                        logger.info(
                            f"✅ [Genesis] Discoverability complete: "
                            f"{audit_summary.get('passed', 0)}/{audit_summary.get('total', 0)} tasks passed, "
                            f"avg LLM score: {audit_summary.get('avg_llm_score', 0)}"
                        )

                        # Store results in spec metadata for later reference
                        spec.metadata["discoverability_result"] = {
                            "audit_summary": audit_summary,
                            "timestamp": discoverability_result.get("timestamp"),
                            "tasks_completed": audit_summary.get("total", 0),
                            "vetoes": audit_summary.get("vetoes", 0)
                        }
                    else:
                        # Fallback to legacy SEO agent
                        logger.warning("[Genesis] DiscoverabilityEngine not available, using legacy SEO agent")
                        from agents.seo_agent import get_seo_agent
                        seo_agent = await get_seo_agent(business_id=business_id)
                        if hasattr(seo_agent, 'configure_seo'):
                            await seo_agent.configure_seo(deployment_url, spec.description)
                            logger.info("✅ [Genesis] Legacy SEO configured")
                except Exception as e:
                    logger.exception(f"[Genesis] Discoverability Engine failed: {e}")

            # Task 4: Stripe Configuration
            if "stripe_billing" in spec.components or "stripe_checkout" in spec.components or "billing_agent" in assigned_agents:
                logger.info("💳 [Genesis] Configuring world-class Stripe billing...")
                try:
                    from agents.billing_agent import get_billing_agent
                    billing_agent = await get_billing_agent(business_id=business_id)
                    if hasattr(billing_agent, 'configure_stripe'):
                        await billing_agent.configure_stripe(deployment_url, spec)
                        logger.info("✅ [Genesis] Stripe billing configured")
                except Exception as e:
                    logger.warning(f"[Genesis] Stripe setup failed: {e}")

            # Task 5: Monitoring Setup
            logger.info("📡 [Genesis] Setting up world-class monitoring and alerts...")
            try:
                # Try to use monitoring agent if available
                from agents.monitoring_agent import get_monitoring_agent
                monitoring_agent = await get_monitoring_agent(business_id=business_id)
                if hasattr(monitoring_agent, 'setup_alerts'):
                    await monitoring_agent.setup_alerts(deployment_url)
                    logger.info("✅ [Genesis] Monitoring configured")
            except Exception as e:
                logger.warning(f"[Genesis] Monitoring setup failed: {e}")

            # Check if custom agents are needed
            custom_agent = await self._determine_if_new_agent_needed(
                website_needs=spec.metadata.get("website_needs", {}),
                existing_agents=assigned_agents
            )
            
            if custom_agent:
                logger.info(f"🔧 [Genesis] Creating custom agent for {deployment_url}...")
                created_agent = await self._create_custom_agent_for_website(
                    agent_type=custom_agent.get("type"),
                    website_url=deployment_url,
                    requirements=custom_agent.get("requirements", {})
                )
                if created_agent:
                    assigned_agents.append(created_agent.metadata.get("agent_id", "custom_agent"))
                    logger.info(f"✅ [Genesis] Custom agent created: {created_agent.name}")
            
            # Initialize day-to-day operations for assigned agents
            await self._initialize_website_operations(
                deployment_url=deployment_url,
                agents=assigned_agents,
                spec=spec
            )

            logger.info(f"✅ [Genesis] World-class post-deployment automation completed for {spec.name}")
            logger.info(f"   Assigned agents: {', '.join(assigned_agents)}")

        except Exception as e:
            logger.error(f"❌ [Genesis] Post-deployment automation failed: {e}")
            import traceback
            traceback.print_exc()
    
    async def _assign_agents_to_website(
        self,
        deployment_url: str,
        spec: BusinessSpec,
        business_id: str
    ) -> List[str]:
        """
        Assign agents to manage day-to-day operations of deployed website.
        
        As the world's best orchestrator, Genesis assigns the perfect agents for
        each website's needs.
        
        Args:
            deployment_url: URL of deployed website
            spec: Business specification
            business_id: Business ID
            
        Returns:
            List of assigned agent names
        """
        assigned_agents = []
        
        try:
            logger.info(f"👥 [Genesis] Assigning world-class agents to {deployment_url}...")
            
            # Always assign Marketing Agent for marketing campaigns
            assigned_agents.append("marketing_agent")
            logger.info("   ✅ Marketing Agent assigned")
            
            # Always assign SEO Agent for ongoing SEO optimization
            assigned_agents.append("seo_agent")
            logger.info("   ✅ SEO Agent assigned")
            
            # Assign Billing Agent if payment processing needed
            if "stripe_billing" in spec.components or "stripe_checkout" in spec.components or spec.metadata.get("enable_billing", False):
                assigned_agents.append("billing_agent")
                logger.info("   ✅ Billing Agent assigned")
            
            # Assign Analytics Agent if analytics component exists
            if "analytics" in spec.components:
                assigned_agents.append("analytics_agent")
                logger.info("   ✅ Analytics Agent assigned")
            
            # Assign Support Agent if customer support needed
            if spec.metadata.get("enable_support", False) or "support" in spec.business_type.lower():
                assigned_agents.append("support_agent")
                logger.info("   ✅ Support Agent assigned")
            
            # Store agent-to-website mapping
            if not hasattr(self, '_website_agent_mapping'):
                self._website_agent_mapping = {}
            
            self._website_agent_mapping[deployment_url] = {
                "agents": assigned_agents,
                "business_id": business_id,
                "spec_name": spec.name,
                "assigned_at": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"✅ [Genesis] Assigned {len(assigned_agents)} agents to {deployment_url}")
            
        except Exception as e:
            logger.error(f"❌ [Genesis] Agent assignment failed: {e}")
        
        return assigned_agents
    
    async def _initialize_website_operations(
        self,
        deployment_url: str,
        agents: List[str],
        spec: BusinessSpec
    ):
        """
        Initialize day-to-day operations for assigned agents.
        
        As the world's best orchestrator, Genesis sets up recurring tasks
        for perfect website management.
        
        Args:
            deployment_url: URL of deployed website
            agents: List of assigned agent names
            spec: Business specification
        """
        try:
            logger.info(f"🔄 [Genesis] Initializing day-to-day operations for {deployment_url}...")
            
            # Set up recurring tasks for each agent type
            operations_config = {
                "marketing_agent": {
                    "daily": ["content_creation_check", "campaign_monitoring"],
                    "weekly": ["campaign_review", "strategy_optimization"],
                    "monthly": ["performance_analysis", "strategy_planning"]
                },
                "seo_agent": {
                    "daily": ["ranking_monitoring", "keyword_tracking"],
                    "weekly": ["keyword_research", "content_optimization"],
                    "monthly": ["seo_report_generation", "strategy_refinement"]
                },
                "analytics_agent": {
                    "daily": ["traffic_monitoring", "conversion_tracking"],
                    "weekly": ["performance_analysis", "trend_identification"],
                    "monthly": ["comprehensive_report", "insights_generation"]
                },
                "billing_agent": {
                    "daily": ["transaction_monitoring", "payment_verification"],
                    "weekly": ["revenue_reports", "subscription_management"],
                    "monthly": ["billing_summaries", "financial_analysis"]
                },
                "support_agent": {
                    "daily": ["ticket_monitoring", "response_tracking"],
                    "weekly": ["satisfaction_metrics", "common_issues_analysis"],
                    "monthly": ["support_reports", "improvement_planning"]
                }
            }
            
            # Store operations configuration
            if not hasattr(self, '_website_operations'):
                self._website_operations = {}
            
            self._website_operations[deployment_url] = {
                "agents": agents,
                "operations": {agent: operations_config.get(agent, {}) for agent in agents},
                "initialized_at": datetime.now(timezone.utc).isoformat(),
                "spec_name": spec.name
            }
            
            logger.info(f"✅ [Genesis] Day-to-day operations initialized for {deployment_url}")
            logger.info(f"   Operations configured for {len(agents)} agents")
            
        except Exception as e:
            logger.error(f"❌ [Genesis] Operations initialization failed: {e}")
    
    async def _determine_if_new_agent_needed(
        self,
        website_needs: Dict[str, Any],
        existing_agents: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Determine if a new custom agent is needed for website operations.
        
        As the world's best orchestrator, Genesis analyzes website needs and
        determines if existing agents can handle all requirements, or if a
        custom agent is needed.
        
        Args:
            website_needs: Dictionary of website needs
            existing_agents: List of existing agent names
            
        Returns:
            Agent specification if new agent needed, None otherwise
        """
        try:
            if not hasattr(self, 'dynamic_agent_creator') or self.dynamic_agent_creator is None:
                return None
            
            # Use DynamicAgentCreator to identify gaps
            gaps = self.dynamic_agent_creator._identify_agent_gaps(
                business_needs=website_needs,
                existing_agents=existing_agents
            )
            
            if not gaps:
                return None
            
            # Return specification for most critical gap
            primary_gap = gaps[0]
            return {
                "type": primary_gap.get("type", "custom"),
                "need": primary_gap.get("need"),
                "requirements": {
                    "need": primary_gap.get("need"),
                    "priority": primary_gap.get("priority", 1)
                }
            }
            
        except Exception as e:
            logger.warning(f"[Genesis] Error determining if new agent needed: {e}")
            return None
    
    async def _create_custom_agent_for_website(
        self,
        agent_type: str,
        website_url: str,
        requirements: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Create a custom agent for website-specific needs.
        
        As the world's best orchestrator, Genesis creates perfect agents
        for any website need using the DynamicAgentCreator.
        
        Args:
            agent_type: Type of agent to create
            website_url: URL of website
            requirements: Agent requirements
            
        Returns:
            Created DynamicAgent or None
        """
        try:
            if not hasattr(self, 'dynamic_agent_creator') or self.dynamic_agent_creator is None:
                logger.warning("[Genesis] DynamicAgentCreator not available")
                return None
            
            # Create agent using DynamicAgentCreator
            agent = await self.dynamic_agent_creator.create_agent_for_website(
                website_url=website_url,
                business_needs={requirements.get("need", "custom"): True},
                existing_agents=[]
            )
            
            if agent:
                logger.info(f"✅ [Genesis] Created custom agent: {agent.name} for {website_url}")
                
                # Register agent if router available
                if hasattr(self, 'router') and self.router:
                    try:
                        # Register agent in router
                        capability = AgentCapability(
                            agent_id=agent.agent_id,
                            capabilities=agent.capabilities,
                            cost_tier=agent.cost_tier,
                            success_rate=agent.success_rate
                        )
                        if hasattr(self.router, 'register_agent'):
                            self.router.register_agent(agent.agent_id, capability)
                            logger.info(f"✅ [Genesis] Registered {agent.agent_id} in router")
                    except Exception as e:
                        logger.warning(f"[Genesis] Failed to register agent: {e}")
            
            return agent
            
        except Exception as e:
            logger.error(f"❌ [Genesis] Failed to create custom agent: {e}")
            return None

    async def _summarize_business_spend(self, business_id: str, spec: BusinessSpec, total_cost: float):
        intents = self.payment_manager.get_business_intents(business_id)
        vendor_breakdown: Dict[str, float] = defaultdict(float)
        agent_breakdown: Dict[str, float] = defaultdict(float)
        approved = 0
        denied = 0
        for intent in intents:
            vendor = intent.metadata.get("vendor") or intent.component
            vendor_breakdown[vendor] += intent.cost_usd
            agent_breakdown[intent.agent] += intent.cost_usd
            if intent.approved:
                approved += 1
            else:
                denied += 1
        projected_revenue = float(spec.metadata.get("projected_revenue") or spec.metadata.get("target_revenue") or 0.0)
        ratio = round((total_cost / projected_revenue), 3) if projected_revenue else None
        roi = round((projected_revenue / total_cost), 3) if total_cost and projected_revenue else None
        summary = {
            "business_id": business_id,
            "business_name": spec.name,
            "total_spent": round(total_cost, 2),
            "approved_intents": approved,
            "denied_intents": denied,
            "vendor_breakdown": vendor_breakdown,
            "agent_breakdown": agent_breakdown,
            "projected_revenue": projected_revenue,
            "spend_to_revenue_ratio": ratio,
            "roi": roi,
            "dashboard_url": spec.metadata.get("deployment_url") or spec.metadata.get("dashboard_url"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._write_spend_summary(summary)
        await self.post_business_spend_summary(summary)

    def _write_spend_summary(self, summary: Dict[str, Any]) -> None:
        SPEND_SUMMARY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SPEND_SUMMARY_LOG.open("a", encoding="utf-8") as fd:
            fd.write(json.dumps(summary) + "\n")

    async def post_business_spend_summary(self, summary: Dict[str, Any]) -> None:
        message = self._format_spend_summary_message(summary)
        await self._send_discord_message("dashboard", message, business_id=summary.get("business_id"))
        if self.discord:
            await self.discord.payment_business_summary(summary)

    async def _send_discord_message(
        self,
        channel: str,
        message: str,
        business_id: Optional[str] = None,
    ) -> None:
        if not self.discord:
            return
        target_business = business_id or self._current_business_id or "meta-agent"
        if channel == "dashboard":
            await self.discord.agent_progress(target_business, "Meta Agent Summary", message)
        else:
            await self.discord.agent_error(target_business, "Meta Agent Summary", message)

    def _format_spend_summary_message(self, summary: Dict[str, Any]) -> str:
        lines = [
            f"💰 Total Spent: ${summary.get('total_spent', 0.0):.2f}",
            f"📈 Projected Revenue: ${summary.get('projected_revenue', 0.0):.2f}",
        ]
        roi = summary.get("roi")
        if roi is not None:
            lines.append(f"💹 ROI: {roi:.2f}x")
        ratio = summary.get("spend_to_revenue_ratio")
        if ratio is not None:
            lines.append(f"🔄 Spend/Revenue Ratio: {ratio:.2f}")
        lines.append(f"✅ Approved intents: {summary.get('approved_intents', 0)}")
        lines.append(f"🚫 Denied intents: {summary.get('denied_intents', 0)}")
        vendor_breakdown = summary.get("vendor_breakdown", {})
        agent_breakdown = summary.get("agent_breakdown", {})
        if vendor_breakdown:
            vendor_lines = ", ".join(f"{vendor}: ${amount:.2f}" for vendor, amount in vendor_breakdown.items())
            lines.append(f"Vendors: {vendor_lines}")
        if agent_breakdown:
            agent_lines = ", ".join(f"{agent}: ${amount:.2f}" for agent, amount in agent_breakdown.items())
            lines.append(f"Agents: {agent_lines}")
        dashboard_url = summary.get("dashboard_url")
        if dashboard_url:
            lines.append(f"🔗 Dashboard: {dashboard_url}")
        return "\n".join(lines)
    async def call_premium_llm(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        response = await self.payment_base._pay(
            "post",
            "https://llm-api.genesis.com/completions",
            self.payment_base.get_cost("call_premium_llm", 1.5),
            json={"model": "gpt-4.5-turbo", "messages": messages},
        )
        return response.json()

    async def optimize_prompt(self, prompt: str) -> Dict[str, Any]:
        response = await self.payment_base._pay(
            "post",
            "https://prompt-optimizer.genesis.com/optimize",
            self.payment_base.get_cost("optimize_prompt", 0.4),
            json={"base_prompt": prompt, "optimization_goal": "reduce_tokens"},
        )
        return response.json()

    def _create_workspace_manager(self, business_id: str, spec: BusinessSpec) -> WorkspaceStateManager:
        """Initialize workspace synthesis manager for the current run."""
        interval = int(os.getenv("WORKSPACE_SYNTHESIS_INTERVAL", "50"))
        return WorkspaceStateManager(
            business_id=business_id,
            persistence_root=spec.output_dir,
            summary_interval=max(5, interval),
            llm_callback=self._workspace_insight_callback,
        )

    async def _workspace_insight_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Use analyst agent to synthesize workspace insights every interval."""
        prompt = (
            "You are Genesis' workspace synthesizer. Analyze the JSON payload summarizing "
            "recent agent progress and produce:\n"
            "1. `workspace_summary`: concise narrative (<=120 words).\n"
            "2. `risks`: list of concrete risks (<=4) or empty.\n"
            "3. `next_actions`: prioritized actions for the orchestrator.\n"
            "Respond with JSON only.\n\n"
            f"Payload:\n```json\n{json.dumps(payload, indent=2)}\n```"
        )

        try:
            response = await self._call_router("analyst_agent", prompt, temperature=0.1)
            if not response:
                raise ValueError("Empty response")
            parsed = json.loads(self._extract_json_block(response))
            if not isinstance(parsed, dict):
                raise ValueError("LLM returned non-dict JSON")
            return parsed
        except Exception as exc:
            logger.warning(f"Workspace insight synthesis failed: {exc}")
            return {
                "workspace_summary": "Analyst synthesis unavailable; using fallback.",
                "risks": [f"Insight callback error: {exc}"],
                "next_actions": [],
            }

    @staticmethod
    def _extract_json_block(raw_response: str) -> str:
        """Extract JSON content from potential code fences."""
        raw_response = raw_response.strip()
        if raw_response.startswith("```"):
            lines = raw_response.splitlines()
            json_lines = [line for line in lines[1:] if not line.startswith("```")]
            return "\n".join(json_lines)
        return raw_response
    
    async def autonomous_generate_business(
        self,
        business_idea: Optional[Any] = None,
        min_score: float = 70.0,
        max_components: int = len(AGENT_COMPONENT_REQUIREMENTS) * 2,
        min_components: int = 10
    ) -> BusinessGenerationResult:
        """
        🤖 FULLY AUTONOMOUS business generation using all Genesis systems.
        
        This is the TRUE autonomous flow that replaces hardcoded templates:
        1. Generate business idea (or use provided one)
        2. Select optimal components using LLM reasoning
        3. Assemble optimal team based on capabilities
        4. Build all components in parallel
        5. Validate and learn
        
        Args:
            business_idea: Optional BusinessIdea object (if None, generates one)
            min_score: Minimum revenue score for generated ideas
            max_components: Maximum components to select
            min_components: Minimum components required
        
        Returns:
            BusinessGenerationResult with all components built
        """
        logger.info("="*80)
        logger.info("🤖 GENESIS: Starting world-class autonomous business generation")
        logger.info("   Genesis - the world's premier orchestrator - is creating a masterpiece")
        logger.info("="*80)
        
        # Lazy load dependencies
        if self.idea_generator is None:
            from infrastructure.business_idea_generator import get_idea_generator
            self.idea_generator = get_idea_generator()
        
        if self.component_selector is None:
            from infrastructure.component_selector import get_component_selector
            self.component_selector = get_component_selector()
        
        if self.team_assembler is None:
            from infrastructure.team_assembler import get_team_assembler
            self.team_assembler = get_team_assembler()
        
        # Step 1: Generate or use business idea
        if business_idea is None:
            logger.info("🎯 Step 1: Genesis generating world-class business idea...")
            idea = await self.idea_generator.generate_idea(min_revenue_score=min_score)
            logger.info(f"✅ Genesis created exceptional idea: '{idea.name}' (score={idea.overall_score:.1f}/100)")
        else:
            idea = business_idea
            logger.info(f"🎯 Step 1: Using provided idea: '{idea.name}'")
        
        # Step 2: Select optimal components using LLM
        logger.info(f"🧩 Step 2: Genesis making perfect technology choices...")
        selection = await self.component_selector.select_components_for_business(
            business_idea=idea,
            max_components=max_components,
            min_components=min_components
        )
        
        components = self._ensure_agent_coverage(
            selection.components,
            max_components=max_components,
        )
        coverage_additions = [c for c in components if c not in selection.components]
        logger.info(f"✅ Selected {len(components)} components (build time: {selection.total_build_time_minutes}min)")
        logger.info(f"   Components: {components}")
        logger.info(f"   Reasoning: {selection.reasoning}")
        if coverage_additions:
            logger.info(f"   Added for agent coverage: {coverage_additions}")
        
        # Step 3: Assemble optimal team
        logger.info(f"👥 Step 3: Genesis assembling world-class team...")
        team_agent_ids = self.team_assembler.assemble_optimal_team(
            components=components,
            business_type=idea.business_type,
            team_size=5
        )
        
        logger.info(f"✅ Team assembled: {team_agent_ids}")
        
        # Step 4: Create business spec with selected components
        business_name_slug = idea.name.lower().replace(' ', '-').replace("'", "")
        output_dir = Path(f"businesses/autonomous/{business_name_slug}")
        
        spec = BusinessSpec(
            name=idea.name,
            business_type=idea.business_type,
            description=idea.description,
            components=components,  # ✅ Uses intelligently selected components
            output_dir=output_dir,
            metadata={
                **idea.to_dict(),
                "component_selection": {
                    "total_components": len(components),
                    "required": selection.required_count,
                    "recommended": selection.recommended_count,
                    "build_time_minutes": selection.total_build_time_minutes,
                    "coverage_additions": coverage_additions,
                },
                "team": team_agent_ids
            }
        )
        
        # Step 5: Generate business using standard flow
        logger.info(f"🔨 Step 4: Genesis orchestrating flawless build of {len(components)} components...")
        logger.info(f"   World-class team: {team_agent_ids}")
        
        result = await self.generate_business(spec)
        
        # Step 6: Log success
        if result.success:
            logger.info("="*80)
            logger.info(f"✅ GENESIS MASTERPIECE COMPLETE: {idea.name}")
            logger.info(f"   Genesis orchestrated flawless build: {len(components)} world-class components")
            logger.info(f"   Perfect execution time: {result.generation_time_seconds:.1f}s")
            logger.info(f"   Production-ready output: {result.output_directory}")
            logger.info("   Genesis - world's best at every aspect - delivers excellence again")
            logger.info("="*80)
        else:
            logger.error(f"❌ Generation failed: {result.errors}")

        return result

    async def _execute_meta_task(self, task_description: str) -> Dict:
        """
        Execute a meta-level orchestration task (used by CuriosityDrivenTrainer).

        Args:
            task_description: Description of orchestration task to execute

        Returns:
            Dict with orchestration output and quality metrics
        """
        try:
            # Simulate meta task execution for training
            # In production, this would orchestrate real business generation
            if "generate business" in task_description.lower():
                # Simulate autonomous business generation
                output = {"business_name": "Training Business", "components_generated": 5}
            elif "select components" in task_description.lower():
                # Simulate component selection
                output = {"components": ["dashboard_ui", "rest_api", "analytics"], "count": 3}
            else:
                output = {"task": task_description, "status": "completed"}

            return output

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Meta task execution failed: {e}")
            return {"error": str(e)}

    def get_integration_status(self) -> Dict:
        """
        Get detailed status of ALL integrations.

        Returns comprehensive report of ALL 110+ integrations (v6.0 Full Integration Release)
        """
        integrations = {
            # Core Agent Framework (5)
            "Azure_AI_Framework": {"enabled": True, "benefit": "Production-grade AI framework"},
            "MS_Agent_Framework": {"enabled": True, "benefit": "Microsoft Agent Framework v4.0"},
            "Agent_Framework_ChatAgent": {"enabled": True, "benefit": "Conversational AI capabilities"},
            "Agent_Framework_Observability": {"enabled": True, "benefit": "Built-in tracing & monitoring"},
            "Agent_Payment_Mixin": {"enabled": True, "benefit": "Payment capabilities for agents"},

            # Cost Optimization & Routing (10)
            "DAAO_Router": {"enabled": bool(self.daao_router), "benefit": "20-30% cost reduction"},
            "DAAO_Optimizer": {"enabled": bool(self.daao_optimizer), "benefit": "Dynamic routing optimization"},
            "TUMIX_Termination": {"enabled": bool(self.termination), "benefit": "50-60% cost savings"},
            "HALO_Router": {"enabled": bool(self.router), "benefit": "Multi-agent coordination"},
            "Autonomous_Orchestrator": {"enabled": bool(self.autonomous_orchestrator), "benefit": "Self-managing workflows"},
            "Darwin_Orchestration_Bridge": {"enabled": bool(self.darwin_orchestration_bridge), "benefit": "SE-Darwin integration"},
            "Dynamic_Agent_Creator": {"enabled": bool(self.dynamic_agent_creator), "benefit": "Runtime agent creation"},
            "AOP_Validator": {"enabled": bool(self.aop_validator), "benefit": "Agent output validation"},
            "Full_System_Integrator": {"enabled": bool(self.full_system_integrator), "benefit": "System-wide coordination"},
            "Cost_Profiler": {"enabled": bool(self.cost_profiler), "benefit": "Detailed cost analysis"},

            # Memory & Learning (15)
            "MemoryOS_Core": {"enabled": True, "benefit": "Core memory framework"},
            "MemoryOS_MongoDB": {"enabled": bool(self.memory), "benefit": "49% F1 improvement"},
            "Memory_Store": {"enabled": bool(self.memory_store), "benefit": "Persistent memory storage"},
            "Agentic_RAG": {"enabled": bool(self.agentic_rag), "benefit": "Agent-driven retrieval"},
            "Reasoning_Bank": {"enabled": bool(self.reasoning_bank), "benefit": "Reasoning pattern repository"},
            "Replay_Buffer": {"enabled": bool(self.replay_buffer), "benefit": "Experience replay for learning"},
            "CaseBank": {"enabled": bool(self.casebank), "benefit": "Failed task repository"},
            "Memento_Agent": {"enabled": bool(self.memento_agent), "benefit": "Temporal memory management"},
            "Graph_Database": {"enabled": bool(self.graph_database), "benefit": "Relationship-based memory"},
            "Embedding_Generator": {"enabled": bool(self.embedding_generator), "benefit": "Semantic embedding creation"},
            "Benchmark_Recorder": {"enabled": bool(self.benchmark_recorder), "benefit": "Performance tracking"},
            "Context_Linter": {"enabled": bool(self.context_linter), "benefit": "Context quality validation"},
            "Context_Profiles": {"enabled": bool(self.context_profiles), "benefit": "User/task profiles"},
            "Token_Cache_Helper": {"enabled": bool(self.token_cache_helper), "benefit": "Token usage optimization"},
            "Token_Cached_RAG": {"enabled": bool(self.token_cached_rag), "benefit": "Cached retrieval"},

            # AgentEvolver (7)
            "AgentEvolver_Phase1": {"enabled": bool(self.self_questioning_engine), "benefit": "Curiosity-driven learning"},
            "AgentEvolver_Phase2": {"enabled": bool(self.experience_buffer), "benefit": "Experience reuse"},
            "AgentEvolver_Phase3": {"enabled": bool(self.contribution_tracker), "benefit": "Self-attribution"},
            "Task_Embedder": {"enabled": bool(self.task_embedder), "benefit": "Task similarity matching"},
            "Hybrid_Policy": {"enabled": bool(self.hybrid_policy), "benefit": "Explore/exploit balance"},
            "Cost_Tracker": {"enabled": bool(self.cost_tracker), "benefit": "Training cost monitoring"},
            "Scenario_Ingestion_Pipeline": {"enabled": bool(self.ingestion_pipeline), "benefit": "Automated scenario collection"},

            # DeepEyes (4)
            "DeepEyes_ToolReliability": {"enabled": bool(self.tool_reliability), "benefit": "Tool success tracking"},
            "DeepEyes_MultimodalTools": {"enabled": bool(self.tool_registry), "benefit": "Multimodal tool registry"},
            "DeepEyes_ToolChainTracker": {"enabled": bool(self.tool_chain_tracker), "benefit": "Tool chain tracking"},
            "DeepEyes_WebSearchTools": {"enabled": bool(self.web_search_toolkit), "benefit": "Web search capabilities"},

            # Web & Browser Automation (8)
            "WebVoyager_Client": {"enabled": bool(self.webvoyager), "benefit": "59.1% web navigation success"},
            "VOIX_Detector": {"enabled": bool(self.voix_detector), "benefit": "10-25x faster web automation"},
            "VOIX_Executor": {"enabled": bool(self.voix_executor), "benefit": "Declarative browser automation"},
            "Computer_Use_Client": {"enabled": bool(self.computer_use), "benefit": "Gemini GUI automation"},
            "DOM_Accessibility_Parser": {"enabled": bool(self.dom_parser), "benefit": "Accessible DOM parsing"},
            "Browser_Automation_Framework": {"enabled": True, "benefit": "Core browser automation"},
            "Hybrid_Automation_Policy": {"enabled": bool(self.hybrid_automation_policy), "benefit": "Smart automation routing"},
            "WebVoyager_System_Prompts": {"enabled": bool(self.webvoyager_prompt_fn), "benefit": "Optimized prompts"},

            # SPICE (Self-Play Evolution) (3)
            "SPICE_Challenger": {"enabled": bool(self.challenger_agent), "benefit": "Challenge generation"},
            "SPICE_Reasoner": {"enabled": bool(self.reasoner_agent), "benefit": "Reasoning verification"},
            "SPICE_DrGRPO_Optimizer": {"enabled": bool(self.drgrpo_optimizer), "benefit": "Self-play optimization"},

            # Payment & Budget (8)
            "AP2_Protocol": {"enabled": True, "benefit": "Budget tracking"},
            "AP2_Helpers": {"enabled": True, "benefit": "AP2 utility functions"},
            "A2A_X402_Service": {"enabled": bool(self.x402_service), "benefit": "Agent-to-agent payments"},
            "Media_Payment_Helper": {"enabled": bool(self.media_helper), "benefit": "Creative asset payments"},
            "Budget_Enforcer": {"enabled": True, "benefit": "Budget limits enforcement"},
            "Stripe_Manager": {"enabled": bool(self.stripe_manager), "benefit": "Stripe payment integration"},
            "Finance_Ledger": {"enabled": bool(self.finance_ledger), "benefit": "Transaction ledger"},
            "X402_Monitor": {"enabled": bool(self.x402_monitor), "benefit": "Payment monitoring"},

            # LLM Providers (6)
            "LLM_Client_Generic": {"enabled": bool(self.llm_generic_client), "benefit": "Generic LLM interface"},
            "Gemini_Client": {"enabled": bool(self.gemini_client), "benefit": "Gemini LLM routing"},
            "DeepSeek_Client": {"enabled": bool(self.deepseek_client), "benefit": "DeepSeek LLM routing"},
            "Mistral_Client": {"enabled": bool(self.mistral_client), "benefit": "Mistral LLM routing"},
            "OpenAI_Client": {"enabled": bool(self.openai_client), "benefit": "OpenAI LLM routing"},
            "Local_LLM_Provider": {"enabled": bool(self.llm_client), "benefit": "Local model support"},

            # Safety & Security (8)
            "WaltzRL_Safety": {"enabled": bool(self.waltzrl_wrapper), "benefit": "Safety wrapper"},
            "WaltzRL_Conversation_Agent": {"enabled": bool(self.waltzrl_conversation), "benefit": "Safe conversation handling"},
            "WaltzRL_Feedback_Agent": {"enabled": bool(self.waltzrl_feedback), "benefit": "Safety feedback"},
            "WaltzRL_Stage2_Trainer": {"enabled": bool(self.waltzrl_stage2_trainer), "benefit": "Advanced safety training"},
            "Agent_Auth_Registry": {"enabled": bool(self.agent_auth_registry), "benefit": "Agent authentication"},
            "Security_Scanner": {"enabled": bool(self.security_scanner), "benefit": "Vulnerability scanning"},
            "PII_Detector": {"enabled": bool(self.pii_detector), "benefit": "PII detection & redaction"},
            "Safety_Wrapper": {"enabled": True, "benefit": "Safety wrapper (via WaltzRL)"},

            # Evolution & Training (7)
            "Memory_Aware_Darwin": {"enabled": bool(self.memory_aware_darwin), "benefit": "Memory-enhanced evolution"},
            "Solver_Agent": {"enabled": bool(self.solver_agent), "benefit": "Problem-solving agent"},
            "Verifier_Agent": {"enabled": bool(self.verifier_agent), "benefit": "Solution verification"},
            "React_Training": {"enabled": bool(self.react_training), "benefit": "ReAct pattern training"},
            "LLM_Judge_RL": {"enabled": bool(self.llm_judge_rl), "benefit": "LLM-based RL"},
            "Environment_Learning_Agent": {"enabled": bool(self.env_learning_agent), "benefit": "Environment adaptation"},
            "Trajectory_Pool": {"enabled": True, "benefit": "Trajectory storage (via TaskDAG)"},

            # Observability & Monitoring (10)
            "Observability": {"enabled": True, "benefit": "OpenTelemetry tracing"},
            "Health_Check": {"enabled": bool(self.health_check), "benefit": "System health monitoring"},
            "Analytics": {"enabled": bool(self.analytics), "benefit": "Usage analytics"},
            "AB_Testing": {"enabled": bool(self.ab_testing), "benefit": "A/B testing framework"},
            "Codebook_Manager": {"enabled": bool(self.codebook_manager), "benefit": "Codebook management"},
            "Modular_Prompts": {"enabled": bool(self.prompt_assembler), "benefit": "Context engineering 2.0"},
            "Benchmark_Runner": {"enabled": bool(self.benchmark_runner), "benefit": "Quality monitoring"},
            "CI_Eval_Harness": {"enabled": bool(self.ci_eval), "benefit": "Continuous evaluation"},
            "Prometheus_Metrics": {"enabled": bool(self.prometheus_metrics), "benefit": "Metrics export"},
            "Discord_Integration": {"enabled": bool(self.discord), "benefit": "Real-time notifications"},

            # Business & Workflow (8)
            "Business_Idea_Generator": {"enabled": True, "benefit": "Autonomous idea generation"},
            "Business_Monitor": {"enabled": True, "benefit": "Business generation tracking"},
            "Component_Selector": {"enabled": True, "benefit": "Intelligent component selection"},
            "Component_Library": {"enabled": True, "benefit": "Component repository"},
            "Genesis_Discord": {"enabled": bool(self.discord), "benefit": "Discord integration"},
            "Task_DAG": {"enabled": True, "benefit": "Task dependency management"},
            "Workspace_State_Manager": {"enabled": True, "benefit": "Workspace synthesis"},
            "Team_Assembler": {"enabled": True, "benefit": "Optimal team assembly"},

            # Integration Systems (10)
            "OmniDaemon_Bridge": {"enabled": bool(self.omnidaemon_bridge), "benefit": "Event-driven runtime (Integration #75)"},
            "AgentScope_Runtime": {"enabled": bool(self.agentscope_runtime), "benefit": "AgentScope integration"},
            "AgentScope_Alias": {"enabled": bool(self.agentscope_alias), "benefit": "Agent aliasing"},
            "OpenHands_Integration": {"enabled": bool(self.openhands_integration), "benefit": "OpenHands integration"},
            "Socratic_Zero_Integration": {"enabled": bool(self.socratic_zero), "benefit": "Socratic Zero integration"},
            "Marketplace_Backends": {"enabled": bool(self.marketplace_backends), "benefit": "Marketplace support"},
            "AATC_System": {"enabled": bool(self.aatc_system), "benefit": "Agent-to-agent coordination"},
            "Feature_Flags": {"enabled": bool(self.feature_flags), "benefit": "Feature flag management"},
            "Error_Handler": {"enabled": bool(self.error_handler), "benefit": "Centralized error handling"},
            "Config_Loader": {"enabled": bool(self.config_loader), "benefit": "Configuration management"},
            "Genesis_Health_Check": {"enabled": bool(self.genesis_health_check), "benefit": "Genesis system health"},
        }

        enabled_count = sum(1 for v in integrations.values() if v["enabled"])
        total_count = len(integrations)

        return {
            "version": "6.0",
            "agent": "GenesisMetaAgent",
            "total_integrations": total_count,
            "enabled_integrations": enabled_count,
            "coverage_percent": round(enabled_count / total_count * 100, 1),
            "integrations": integrations,
            "experience_buffer_size": len(self.experience_buffer.experiences) if self.experience_buffer else 0,
            "cost_savings": self.cost_tracker.get_savings() if self.cost_tracker else {"status": "disabled"}
        }

    async def handle_user_conversation(
        self,
        message: str,
        session_id: str,
        user_id: str,
        attachments: Optional[List[str]] = None,
        agent_name: str = "genesis_agent"
    ) -> Dict[str, Any]:
        """
        Handle user conversation with memory integration (Tier 1 - Critical).

        This method provides full memory persistence for user conversations:
        - Stores user messages in Memori (scope: user)
        - Queries user conversation history for context
        - Processes multimodal attachments (images/audio) via Gemini
        - Enforces per-user ACL
        - Persists sessions across restarts

        Args:
            message: User message text
            session_id: Session ID for conversation continuity
            user_id: User ID for ACL and memory isolation
            attachments: Optional list of attachment URIs (images/audio)
            agent_name: Agent to route conversation to (default: genesis_agent)

        Returns:
            Dict with:
                - response: Agent response text
                - history: Conversation history (last 10 messages)
                - multimodal_results: Processed attachments
                - session_context: Session metadata
                - processing_time_ms: Total processing time

        Example:
            result = await agent.handle_user_conversation(
                message="Tell me about my recent projects",
                session_id="session_123",
                user_id="user_456",
                attachments=["screenshot.png"]
            )

            print(result["response"])  # Agent response
            print(result["history"])    # Last 10 messages
        """
        if not self.enable_memory or not self.memory_integration:
            # Fallback: Handle without memory
            logger.warning("Memory integration disabled, running without persistent memory")

            # Direct LLM call without memory
            prompt = f"User request: {message}\n\nProvide a helpful response."
            response = await self._call_router(agent_name, prompt, temperature=0.7)

            return {
                "response": response,
                "history": [],
                "multimodal_results": [],
                "session_context": None,
                "processing_time_ms": 0.0,
                "memory_enabled": False
            }

        # Process message with full memory integration
        start_time = time.time()

        # 1. Handle message with memory integration
        memory_result = await self.memory_integration.handle_user_message(
            message=message,
            session_id=session_id,
            user_id=user_id,
            attachments=attachments,
            retrieve_history=True,
            history_window=10
        )

        processed_message = memory_result["processed_message"]
        history = memory_result["history"]

        # 2. Build context-aware prompt
        context_parts = []

        # Add conversation history
        if history:
            context_parts.append("## Conversation History:")
            for msg in history[-5:]:  # Last 5 messages for context
                role_label = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role_label}: {msg['content'][:200]}")  # Truncate long messages

        # Add multimodal content
        if memory_result["multimodal_results"]:
            context_parts.append("\n## Attachments:")
            for result in memory_result["multimodal_results"]:
                if result["content"]:
                    context_parts.append(f"- {result['type']}: {result['content'][:200]}")

        # Build full prompt
        context_str = "\n".join(context_parts) if context_parts else ""

        full_prompt = f"""You are Genesis, an AI assistant helping the user with their request.

{context_str}

## Current Request:
{processed_message}

Provide a helpful, contextual response based on the conversation history and any attachments."""

        # 3. Generate response via HALO router
        response = await self._call_router(
            agent_name=agent_name,
            prompt=full_prompt,
            temperature=0.7
        )

        if not response:
            response = "I apologize, but I'm unable to generate a response right now. Please try again."

        # 4. Store assistant response
        await self.memory_integration.store_assistant_response(
            response=response,
            session_id=session_id,
            user_id=user_id,
            metadata={
                "agent_name": agent_name,
                "has_attachments": bool(attachments),
                "history_count": len(history)
            }
        )

        processing_time_ms = (time.time() - start_time) * 1000

        return {
            "response": response,
            "history": history,
            "multimodal_results": memory_result["multimodal_results"],
            "session_context": memory_result["session_context"],
            "processing_time_ms": processing_time_ms,
            "memory_enabled": True
        }

    # ============================================================================
    # DIRECT LLM METHODS WITH EXCELLENCE INSTRUCTIONS
    # ============================================================================

    async def analyze_business_strategy(self, spec: BusinessSpec) -> Dict[str, Any]:
        """
        Analyze business generation strategy using world-class architect excellence.

        Uses DirectLLM with 'architect' excellence instructions to evaluate:
        - Technical feasibility
        - Component dependencies
        - Integration requirements
        - Deployment strategy
        - Risk assessment
        """
        try:
            instructions = get_system_instructions().get("architect", get_system_instructions()["builder"])

            prompt = f"""Analyze this business generation request and provide strategic guidance.

Business Specification:
- Name: {spec.name}
- Type: {spec.business_type}
- Description: {spec.description}
- Components: {spec.components}
- Stack: {getattr(spec, 'tech_stack', 'Not specified')}

Provide comprehensive analysis:
1. Technical Feasibility (score 1-10 with reasoning)
2. Component Dependencies (list all dependencies and potential conflicts)
3. Integration Requirements (external services, APIs, databases needed)
4. Deployment Strategy (recommended platforms, scaling considerations)
5. Risk Assessment (technical risks, timeline risks, cost risks)
6. Success Probability (percentage with confidence interval)
7. Recommendations (top 3 recommendations for success)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash-exp",  # Complex strategic analysis
                max_tokens=4096
            )

            logger.info(f"[GenesisMetaAgent] Generated business strategy analysis for {spec.name}")
            return {"status": "success", "analysis": response, "spec": spec.name}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Business strategy analysis failed: {e}")
            return {"status": "failed", "error": str(e), "spec": spec.name}

    async def generate_component_integration_plan(self, components: List[str], business_type: str) -> Dict[str, Any]:
        """
        Generate integration plan for business components using architect excellence.

        Creates detailed integration plan showing how components work together.
        """
        try:
            instructions = get_system_instructions().get("architect", get_system_instructions()["builder"])

            prompt = f"""Design integration architecture for business components.

Business Type: {business_type}
Components: {', '.join(components)}

Generate comprehensive integration plan:
1. Data Flow Diagram (describe how data flows between components)
2. API Contract Specifications (list all APIs with inputs/outputs)
3. Database Schema Design (tables, relationships, indexes)
4. Authentication & Authorization (how users/services authenticate)
5. Event-Driven Architecture (events, publishers, subscribers)
6. Caching Strategy (what to cache, where, invalidation)
7. Error Handling & Fallbacks (failure modes and recovery)
8. Performance Optimization (bottlenecks and solutions)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash-exp",  # Complex architecture design
                max_tokens=4096
            )

            logger.info(f"[GenesisMetaAgent] Generated integration plan for {len(components)} components")
            return {"status": "success", "plan": response, "components": components}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Integration plan generation failed: {e}")
            return {"status": "failed", "error": str(e), "components": components}

    async def optimize_workflow_coordination(self, tasks: List[str], dependencies: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Optimize workflow coordination and task scheduling using architect excellence.

        Analyzes task dependencies and generates optimal execution plan.
        """
        try:
            instructions = get_system_instructions().get("architect", get_system_instructions()["builder"])

            prompt = f"""Optimize task execution workflow for business generation.

Tasks: {json.dumps(tasks)}
Dependencies: {json.dumps(dependencies)}

Provide optimization plan:
1. Parallel Execution Groups (which tasks can run in parallel)
2. Critical Path Analysis (longest sequential path)
3. Resource Allocation (which agents/resources per task)
4. Time Estimates (estimated duration per task and total)
5. Failure Recovery (what happens if a task fails)
6. Monitoring Strategy (key metrics to track)
7. Optimization Opportunities (how to speed up execution)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash-exp",  # Complex workflow optimization (Gemini primary)
                max_tokens=4096
            )

            logger.info(f"[GenesisMetaAgent] Generated workflow optimization for {len(tasks)} tasks")
            return {"status": "success", "optimization": response, "task_count": len(tasks)}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Workflow optimization failed: {e}")
            return {"status": "failed", "error": str(e), "task_count": len(tasks)}

    async def assess_deployment_readiness(self, business_id: str, components_built: List[str]) -> Dict[str, Any]:
        """
        Assess deployment readiness using deployment excellence.

        Evaluates if business is ready for production deployment.
        """
        try:
            instructions = get_system_instructions().get("deployment", get_system_instructions()["backend"])

            prompt = f"""Assess deployment readiness for business.

Business ID: {business_id}
Components Built: {', '.join(components_built)}

Provide deployment readiness assessment:
1. Completeness Check (are all required components present?)
2. Quality Gates (do components meet quality standards?)
3. Security Audit (are there security vulnerabilities?)
4. Performance Baseline (expected performance metrics)
5. Deployment Checklist (pre-flight checklist items)
6. Go/No-Go Recommendation (ready to deploy? yes/no with reasoning)
7. Post-Deployment Plan (monitoring, rollback strategy)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash",  # Fast deployment assessment
                max_tokens=2048
            )

            logger.info(f"[GenesisMetaAgent] Generated deployment readiness assessment for {business_id}")
            return {"status": "success", "assessment": response, "business_id": business_id}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Deployment readiness assessment failed: {e}")
            return {"status": "failed", "error": str(e), "business_id": business_id}

    async def generate_agent_orchestration_strategy(self, required_capabilities: List[str]) -> Dict[str, Any]:
        """
        Generate agent orchestration strategy using architect excellence.

        Determines which agents to use and how to coordinate them.
        """
        try:
            instructions = get_system_instructions().get("architect", get_system_instructions()["builder"])

            prompt = f"""Design agent orchestration strategy for business generation.

Required Capabilities: {', '.join(required_capabilities)}

Available Agents: Frontend, Backend, Database, Architecture, QA, Security, SEO, Marketing,
Content, Deploy, Finance, Legal, Support, and 12 more specialized agents.

Generate orchestration strategy:
1. Agent Selection (which agents to use for each capability)
2. Execution Order (sequential steps and parallel groups)
3. Communication Protocol (how agents share data and coordinate)
4. Conflict Resolution (how to handle agent disagreements)
5. Quality Assurance (how to verify agent outputs)
6. Cost Optimization (which agents to use for cost efficiency)
7. Timeline Estimation (total time with breakdown by agent)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash-exp",  # Complex orchestration design
                max_tokens=4096
            )

            logger.info(f"[GenesisMetaAgent] Generated orchestration strategy for {len(required_capabilities)} capabilities")
            return {"status": "success", "strategy": response, "capabilities": required_capabilities}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Orchestration strategy generation failed: {e}")
            return {"status": "failed", "error": str(e), "capabilities": required_capabilities}

    async def evaluate_business_viability(self, spec: BusinessSpec, market_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Evaluate business viability using business analysis excellence.

        Comprehensive business analysis including market fit, monetization, growth.
        """
        try:
            instructions = get_system_instructions().get("marketing", get_system_instructions()["builder"])

            market_context = json.dumps(market_data) if market_data else "No market data provided"

            prompt = f"""Evaluate business viability and market potential.

Business Specification:
- Name: {spec.name}
- Type: {spec.business_type}
- Description: {spec.description}

Market Context: {market_context}

Provide comprehensive business evaluation:
1. Market Fit Analysis (target market, competition, differentiation)
2. Monetization Strategy (revenue models, pricing, unit economics)
3. Growth Potential (market size, growth rate, scaling strategy)
4. Customer Acquisition (channels, CAC, conversion funnel)
5. Risk Factors (market risks, execution risks, competitive threats)
6. Success Metrics (KPIs to track, targets for 6/12/24 months)
7. Viability Score (1-10 with detailed justification)"""

            response = await call_llm_with_instructions(
                prompt,
                instructions,
                model="gemini-2.0-flash-exp",  # Complex business analysis
                max_tokens=4096
            )

            logger.info(f"[GenesisMetaAgent] Generated business viability evaluation for {spec.name}")
            return {"status": "success", "evaluation": response, "spec": spec.name}

        except Exception as e:
            logger.error(f"[GenesisMetaAgent] Business viability evaluation failed: {e}")
            return {"status": "failed", "error": str(e), "spec": spec.name}
