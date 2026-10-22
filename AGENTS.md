# Azdemy Learning Recommendation Demo

## Goal

Build a demonstration application for personalized employee education
recommendations and read-only education consultation.

This is a demo application, not a production system.

## Source of truth

The primary requirement document is:

`docs/requirements.md`

Read it before making architecture or implementation decisions.

Requirement IDs such as REC, AGT, DAT, MOD, PIP, and SEC should be
preserved when planning implementation and tests.

## Development approach

Use a lightweight planning-first workflow.

For substantial features:

1. Understand the relevant requirements.
2. Surface important assumptions.
3. Propose the simplest design.
4. Distinguish real and mocked components.
5. Define observable acceptance criteria.
6. Create a small implementation plan.
7. Implement one vertical slice at a time.
8. Verify actual behavior before declaring completion.

This is a demo.

Prefer simplicity over production-oriented abstraction.

## Microsoft Foundry

The education consultation agent MUST use Microsoft Foundry Agent Service.

Prefer a Prompt Agent when instructions and supported tools satisfy the
requirements.

Do not introduce a Hosted Agent, custom runtime, or multi-agent
orchestration unless the approved requirements require them.

The consultation agent is read-only.

Authorization and business rules must be enforced by APIs or tools,
not only by the agent instructions.

## Initial demo

The demo should demonstrate:

1. A learner viewing their own recommendations.
2. Cold-start fallback recommendations.
3. Exclusion of closed or ineligible courses.
4. Recommendation reason explanation.
5. Course information lookup and comparison.
6. Grounded education consultation.
7. Explicit unauthorized, no-result, stale-data, and system-error states.

## Mocks

Synthetic data MUST be used.

The initial demo may mock:

- Fabric recommendation generation
- production serving storage
- employee identity
- on-premises source systems
- production private networking

Microsoft Foundry should be used for the integrated consultation-agent
scenario.

## Out of scope

Do not introduce these without an explicit requirement:

- Azure Machine Learning
- real-time model retraining
- real-time personalization
- course enrollment or cancellation
- HR information updates
- write-capable agent tools
- multi-agent orchestration

## Rules

Do not invent:

- Azure regions
- service SKUs
- capacity
- performance targets
- data-residency conclusions
- unsupported Private Link configurations

Record unresolved decisions rather than silently choosing an option.