"""
ADK Web UI entry point — exposes a SequentialAgent as root_agent for `adk web`.

Note: The ADK web UI uses the native SequentialAgent (single session, full
history accumulation). For context-isolated execution, use investigate()
from orchestrator.py instead.

    cd operate
    .venv/bin/adk web agentic_ops_v3 --port 8076
"""

from google.adk.agents import SequentialAgent, ParallelAgent

from .agents.triage import create_triage_agent
from .agents.tracer import create_tracer_agent
from .agents.dispatcher import create_dispatch_agent
from .agents.ims_specialist import create_ims_specialist
from .agents.transport_specialist import create_transport_specialist
from .agents.core_specialist import create_core_specialist
from .agents.subscriber_data_specialist import create_subscriber_data_specialist
from .agents.synthesis import create_synthesis_agent

root_agent = SequentialAgent(
    name="InvestigationDirector",
    description="Multi-phase troubleshooting pipeline (v3).",
    sub_agents=[
        create_triage_agent(),
        create_tracer_agent(),
        create_dispatch_agent(),
        ParallelAgent(
            name="SpecialistTeam",
            description="Parallel specialist execution.",
            sub_agents=[
                create_ims_specialist(),
                create_transport_specialist(),
                create_core_specialist(),
                create_subscriber_data_specialist(),
            ],
        ),
        create_synthesis_agent(),
    ],
)
