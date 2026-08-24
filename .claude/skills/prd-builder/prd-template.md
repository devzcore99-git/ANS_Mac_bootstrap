# 📄 PRODUCT REQUIREMENTS DOCUMENT (PRD)

# LLM / AI-Agent Optimized

> Status: DRAFT — sections still containing `<angle brackets>` are unanswered.

## 1. Project Overview

### 1.1 Project Name

<Clear, short name>

### 1.2 One-Sentence Summary

<What this project does in one sentence, written for a non-technical person>

### 1.3 Problem Statement

- What problem exists today?
- Who experiences it?
- Why existing solutions are insufficient?

### 1.4 Target Users

- Primary user:
- Secondary users (if any):
- Skill level assumptions (beginner / intermediate / expert):

### 1.5 Prior Art & Existing Code

- Existing projects to reuse or extend:
- Reference implementations worth studying:
- What is deliberately being rebuilt rather than reused, and why:

---

## 2. Goals & Success Criteria

### 2.1 Primary Goals (Must Have)

- Goal 1:
- Goal 2:
- Goal 3:

### 2.2 Secondary Goals (Nice to Have)

- Optional Goal 1:
- Optional Goal 2:

### 2.3 Explicit Non-Goals (Out of Scope)

> These features must NOT be implemented.

- Non-goal 1:
- Non-goal 2:
- Non-goal 3:

### 2.4 Success Metrics

> Measurable, so completion is verifiable rather than a judgement call.

- Metric 1 (what is measured, target value, how it is checked):
- Metric 2:

### 2.5 Definition of Done

The project is considered complete when:

- [ ] All required features are implemented
- [ ] Code runs without errors on every target platform
- [ ] Clear setup and usage documentation exists
- [ ] Core edge cases are handled
- [ ] Tests exist for critical logic (if applicable)
- [ ] Success metrics in 2.4 are met

---

## 3. Functional Requirements

### 3.1 Core Features

For each feature, define:

**Feature Name**

- Description:
- Inputs:
- Outputs:
- Expected behavior:
- Error conditions:
- Priority (must / should / could):

(Repeat for each feature)

---

## 4. Interface & User Experience

### 4.1 Interface Type

- CLI / GUI / web / API / library / background service:
- Rationale:

### 4.2 Interaction Model

- Primary workflow, start to finish:
- Input method (flags, prompts, config file, HTTP):
- Output format (human-readable, JSON, file, notification):

### 4.3 Presentation Rules

- Formatting, colour, verbosity expectations:
- Quiet/verbose modes:
- Accessibility considerations (if user-facing):

---

## 5. Non-Functional Requirements

### 5.1 Performance

- Expected scale (users, requests, data size):
- Latency or responsiveness expectations:

### 5.2 Reliability

- Failure handling expectations:
- Retry or recovery behavior:

### 5.3 Security

- Authentication requirements:
- Authorization model:
- Data sensitivity considerations:

### 5.4 Maintainability

- Code readability expectations:
- Modularity requirements:
- Logging / observability expectations:

---

## 6. Technical Constraints & Preferences

### 6.1 Target Platforms

- Operating systems that must be supported:
- Runtime versions that can be assumed present:
- Prerequisites acceptable to require from the user:

### 6.2 Required Technology

- Language(s):
- Frameworks:
- Runtime environment:

### 6.3 Preferred (But Optional) Technology

- Libraries:
- Tools:
- Patterns (e.g., MVC, Clean Architecture):

### 6.4 Explicitly Forbidden Technologies

> These must not be used.

- Forbidden tool 1:
- Forbidden library 2:

---

## 7. External Dependencies & Credentials

### 7.1 Third-Party Services

For each: name, what it is used for, and what happens when it is unavailable.

- Service 1:

### 7.2 Secrets & Configuration

- Credentials required:
- How they are supplied (env var, keychain, config file):
- What must never be written to disk or logs:

### 7.3 Offline Behavior

- Does the system need to work without network access?

---

## 8. Architecture Expectations

### 8.1 High-Level Architecture

- Monolith / Modular / Microservice:
- Client-server boundaries:
- Data flow overview:

### 8.2 Project Structure

Expected directory structure (example):

```
/src
  /core
  /services
  /api
/tests
/docs
```

### 8.3 State Management

- How state should be stored and accessed:

---

## 9. Data Model

### 9.1 Core Entities

For each entity:

- Name:
- Fields:
- Relationships:
- Validation rules:

### 9.2 Data Lifecycle

- Where data is persisted:
- Retention (how long, what prunes it):
- Backup expectations:
- Schema migration approach:

---

## 10. Deployment & Distribution

### 10.1 Installation

- How the user installs it:
- Packaging format (script, binary, container, package manager):

### 10.2 Execution

- How it is launched (manual, scheduled, service):
- Scheduling mechanism if recurring (cron, launchd, Task Scheduler):

### 10.3 Updates

- How updates are delivered:

---

## 11. Edge Cases & Failure Scenarios

The system must explicitly handle:

- Edge case 1:
- Edge case 2:
- Invalid input scenarios:
- Partial failure scenarios:

---

## 12. Testing Strategy

### 12.1 Required Tests

- Unit tests for:
- Integration tests for:
- Mocking requirements:

### 12.2 Manual Test Scenarios

- Scenario 1:
- Scenario 2:

---

## 13. Documentation Requirements

The AI must produce:

- README with setup instructions
- Configuration documentation
- Example usage
- Assumptions & tradeoffs

---

## 14. Risks & Assumptions

### 14.1 Assumptions

> Things taken as true without verification. If one is wrong, the plan changes.

- Assumption 1:

### 14.2 Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
|      |           |        |            |

---

## 15. AI-Agent Instructions (Critical)

### 15.1 Planning First

Before writing code:

1. Summarize understanding of the problem
2. Propose an architecture
3. Identify risks and ambiguities
4. Ask clarification questions **if anything is unclear**

### 15.2 Implementation Rules

- Do not write placeholder code
- Do not omit error handling
- Prefer clarity over cleverness
- Explain design decisions briefly

### 15.3 Iteration Model

- Build the project in logical stages
- Pause after each major stage for review
- Do not assume unstated requirements

---

## 16. Open Questions

> Anything unresolved at the end of the interview. An implementing agent must
> ask about these rather than guessing.

(Leave blank if none, otherwise list here)
