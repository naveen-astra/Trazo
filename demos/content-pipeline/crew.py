"""Content-pipeline demo crew (TRZ-P3-03, CrewAI): researcher/writer/
editor, 15 tasks, one delegation, 5 tool calls.

Realism bar (TASKS/PHASE_3.md's Phase 3 checkpoint): CrewAI's ``step`` is
one ``Task`` (TRZ-P3-01's adapter maps ``TaskStartedEvent``/
``TaskCompletedEvent`` to ``step.started``/``step.finished`` regardless of
how many LLM/tool rounds happen inside it), so hitting "≥15 steps" here
means 15 actual ``Task`` objects, not 15 LLM turns — 4 research tasks + 6
writing tasks + 5 editing tasks. 3 distinct agent roles clears "≥2
agents/roles"; 4 web_search + 1 word_count clears "≥5 tool calls"; the
writer's delegation task clears the "delegation" requirement from this
demo's own task description (memory events are already covered by the
research-assistant demo — this crew has none of its own, matching its own
task description, which doesn't mention memory).
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from llm import ScriptedLLM
from tools import fetch_style_guide, web_search, word_count


def build_crew() -> Crew:
    llm = ScriptedLLM(model="fixture-v1")

    researcher = Agent(
        role="Researcher",
        goal="Gather accurate facts about Trazo",
        backstory="A careful researcher who verifies every claim.",
        llm=llm,
        tools=[web_search],
        allow_delegation=False,
        verbose=False,
    )
    writer = Agent(
        role="Writer",
        goal="Draft clear, well-organized content",
        backstory="A writer who turns research into readable prose.",
        llm=llm,
        allow_delegation=True,
        verbose=False,
    )
    editor = Agent(
        role="Editor",
        goal="Polish content to house style",
        backstory="An editor focused on grammar, clarity, and consistency.",
        llm=llm,
        tools=[fetch_style_guide, word_count],
        allow_delegation=False,
        verbose=False,
    )

    research_overview = Task(
        description="[research_overview] Research an overview of Trazo.",
        expected_output="A one-sentence overview.",
        agent=researcher,
    )
    research_details = Task(
        description=(
            "[research_details] Research technical details of Trazo's event model."
        ),
        expected_output="A one-sentence technical detail.",
        agent=researcher,
    )
    research_examples = Task(
        description="[research_examples] Research a usage example of Trazo.",
        expected_output="A one-sentence example.",
        agent=researcher,
    )
    fact_check_draft = Task(
        description=(
            "[fact_check_draft] Fact-check the technical details before drafting."
        ),
        expected_output="A confirmation the facts check out.",
        agent=researcher,
        context=[research_details],
    )

    outline = Task(
        description="[outline] Outline the article from the research findings.",
        expected_output="A short outline.",
        agent=writer,
        context=[research_overview, research_details, research_examples],
    )
    draft_introduction = Task(
        description="[draft_introduction] Draft the introduction section.",
        expected_output="An introduction paragraph.",
        agent=writer,
        context=[outline],
    )
    draft_body = Task(
        description="[draft_body] Draft the body section.",
        expected_output="A body paragraph.",
        agent=writer,
        context=[outline, fact_check_draft],
    )
    draft_conclusion = Task(
        description="[draft_conclusion] Draft the conclusion section.",
        expected_output="A conclusion paragraph.",
        agent=writer,
        context=[draft_body],
    )
    delegate_to_researcher_for_gap = Task(
        description=(
            "[delegate_to_researcher_for_gap] Confirm one open fact with the "
            "researcher before finalizing the body section."
        ),
        expected_output="A confirmation the gap is resolved.",
        agent=writer,
        context=[draft_body],
    )
    self_review = Task(
        description="[self_review] Review the full draft for internal consistency.",
        expected_output="A consistency confirmation.",
        agent=writer,
        context=[draft_introduction, draft_body, draft_conclusion],
    )

    edit_grammar = Task(
        description="[edit_grammar] Check the draft for grammar issues.",
        expected_output="A grammar confirmation.",
        agent=editor,
        context=[self_review],
    )
    edit_clarity = Task(
        description="[edit_clarity] Check the draft for clarity issues.",
        expected_output="A clarity confirmation.",
        agent=editor,
        context=[self_review],
    )
    edit_consistency = Task(
        description=(
            "[edit_consistency] Check terminology consistency across the draft."
        ),
        expected_output="A consistency confirmation.",
        agent=editor,
        context=[self_review],
    )
    proofread = Task(
        description="[proofread] Proofread the final draft and check its length.",
        expected_output="A proofreading confirmation.",
        agent=editor,
        context=[edit_grammar, edit_clarity, edit_consistency],
    )
    finalize_formatting = Task(
        description=(
            "[finalize_formatting] Apply house-style formatting to the final draft."
        ),
        expected_output="A formatted final draft.",
        agent=editor,
        context=[proofread],
    )

    return Crew(
        agents=[researcher, writer, editor],
        tasks=[
            research_overview,
            research_details,
            research_examples,
            fact_check_draft,
            outline,
            draft_introduction,
            draft_body,
            draft_conclusion,
            delegate_to_researcher_for_gap,
            self_review,
            edit_grammar,
            edit_clarity,
            edit_consistency,
            proofread,
            finalize_formatting,
        ],
        process=Process.sequential,
        verbose=False,
    )
