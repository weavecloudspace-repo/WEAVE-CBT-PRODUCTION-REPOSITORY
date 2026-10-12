# CBT Repository — Mandatory Agent Instructions

READ THIS FILE COMPLETELY BEFORE PERFORMING ANY ACTION IN THIS REPOSITORY.

These instructions apply to every AI coding agent, automated contributor, or development assistant working on this project.

Do not modify code before understanding the relevant existing architecture.

## 1. Understand the Product Boundary

This repository is the local Computer-Based Testing runtime for Weave.

The CBT application is installed on infrastructure controlled by each school.

The school owns:

* the local CBT server;
* the CBT PostgreSQL database;
* exam questions;
* answer keys;
* question banks;
* exam schedules;
* candidate attempts;
* candidate answers;
* local examination results;
* local examination audit records.

Weave does NOT own the school's exam database.

Weave remains authoritative for:

* tenants;
* administrators;
* teachers;
* students;
* student enrollment;
* teacher class-subject assignments;
* sessions/terms;
* assessment schemes/components;
* grading scales;
* final academic result records.

Do not blur these boundaries.

## 2. Do Not Turn CBT Into Another Weave Backend

Only reproduce data from Weave when the CBT runtime genuinely requires a local projection for examination execution.

Do NOT recreate complete Weave domains such as:

* parent management;
* billing;
* subscriptions;
* school configuration;
* complete teacher lifecycle;
* complete student lifecycle;
* report-card management;
* attendance;
* messaging.

Use external Weave identifiers/projections instead.

## 3. Maintain Domain-Oriented Architecture

Business logic should remain inside the appropriate domain.

Expected domains include concepts equivalent to:

* node;
* identity;
* academics;
* questions;
* exams;
* candidates;
* scheduling;
* attempts;
* results;
* synchronization;
* audit.

Do not place unrelated functionality into large generic utility/service files.

Each mature domain should normally expose clearly separated responsibilities such as:

* models;
* schemas;
* repository/persistence;
* services/domain logic;
* routes;
* enums;
* domain exceptions.

Follow existing repository conventions where they have already been established.

## 4. Route → Service → Repository

FastAPI routes must remain thin.

Routes should primarily:

* validate request transport concerns;
* resolve dependencies/authentication;
* call application/domain services;
* serialize responses.

Do NOT put complex exam logic directly inside route handlers.

Business rules belong in services/domain logic.

Database access belongs in repositories/data-access layers where the existing architecture uses that pattern.

## 5. Database Correctness Comes First

PostgreSQL is the durable source of truth for the local CBT runtime.

Critical state such as:

* exam attempts;
* candidate answers;
* exam results;
* candidate eligibility;
* question allocation;

must never exist only in Redis or process memory.

Use appropriate:

* foreign keys;
* unique constraints;
* indexes;
* transactions;
* row locking or optimistic concurrency where required.

Do not rely solely on Python checks for invariants that PostgreSQL can enforce.

## 6. Redis Is Not Durable Examination Storage

Redis may be used for:

* caching;
* short-lived coordination;
* exam status;
* eligibility cache;
* runtime metadata;
* rate limiting;
* performance optimization.

Do NOT store the only copy of candidate answers, attempts, or final results in Redis.

Rule:

Redis = speed.

PostgreSQL = truth.

## 7. Preserve Offline/Local Execution

An active examination must not depend on Weave being continuously available.

Do not introduce runtime behavior that requires:

Candidate
→ CBT Server
→ Weave
→ CBT Server

for ordinary exam operations.

Once the required candidate/exam configuration exists locally, the local CBT server should be capable of:

* candidate login;
* attempt creation;
* question delivery;
* answer persistence;
* attempt resume;
* submission;
* scoring;

without contacting Weave.

## 8. Weave Integration Must Be Explicit

All communication with Weave must be routed through the dedicated Weave integration layer.

Do not scatter direct `httpx`/HTTP calls throughout domains.

The integration boundary should handle concerns such as:

* Weave API client;
* machine/node authentication;
* Weave-issued token validation;
* integration schemas/contracts;
* retries/timeouts;
* integration-specific errors.

Domain services should depend on explicit integration abstractions rather than hardcoded URLs.

## 9. Do Not Access Weave's Database Directly

The CBT application must NEVER connect directly to Weave's production PostgreSQL database.

All cross-system communication must happen through authenticated APIs/contracts.

Similarly, Weave must not directly connect to the local CBT PostgreSQL database.

## 10. Teacher Authorization Comes From Weave

Teachers may only author questions/exams for class-subject assignments they are legitimately assigned to in Weave.

Never authorize teacher exam creation merely because:

`role == teacher`

Authorization must include the relevant class-subject assignment.

Do not invent a completely separate teacher-assignment system inside CBT.

## 11. Admin Controls Exam Finalization

Teachers author and submit examinations.

Tenant administrators control final examination authority.

Admins are responsible for actions such as:

* reviewing submitted exams;
* sealing/finalizing exams;
* scheduling;
* candidate administration;
* PIN administration;
* activation;
* exceptional attempt management.

Teachers must not be given sealing/activation permissions unless the product requirements are explicitly changed.

## 12. Exam Content Must Become Immutable After Finalization

Once an exam is sealed/finalized, do not silently mutate its question content.

If content must change, follow a versioning/reseal lifecycle.

Never allow candidates participating in the same exam version to unknowingly receive different revisions caused by later edits.

## 13. Question Allocation Is Attempt-Specific

Randomized question selection must eventually be generated once when an attempt begins and persisted.

Do NOT re-randomize questions every time the frontend requests them.

An attempt must preserve:

* allocated question IDs;
* display order;
* option ordering where applicable;
* exam version.

This is required so a candidate can resume after:

* power loss;
* browser crash;
* refresh;
* switching computers.

## 14. Candidate Attempts Belong to Candidates, Not Devices

A physical student computer is disposable.

An `ExamAttempt` belongs to:

candidate + exam

not:

candidate + computer.

If a computer fails, the candidate must be able to resume the existing attempt from another machine according to exam policy.

Do not design candidate progress around browser sessions alone.

## 15. Candidate Answer Persistence Must Be Durable

Frontend/browser persistence may be used as an additional resilience layer.

However, the local server must periodically receive and persist answer checkpoints.

Do not design the system so an entire examination exists only in browser local storage until final submission.

## 16. Authoritative Scoring Is Server-Side

Never trust the frontend to calculate the official examination result.

Correct answers and authoritative scoring logic must remain on the local backend.

The browser sends candidate selections.

The backend determines the score.

## 17. CBT Does Not Own Weave Grading

CBT should produce raw examination scores.

Example:

student = X
assessment_component = CA1
raw_score = 8
maximum_score = 10

CBT must not attempt to reproduce Weave's:

* complete assessment aggregation;
* report-card generation;
* grading scale logic.

Weave owns final academic interpretation.

## 18. Build Future Randomization Correctly

Do not assume every exam consists of one static fixed question list.

The architecture should support:

Exam
→ Question Pool(s)
→ Selection Rules
→ Candidate Attempt
→ Persisted Question Allocation

Future rules may include:

* number of questions selected;
* subject/topic sections;
* difficulty;
* marks;
* independent option shuffling.

Avoid schema decisions that make question pools difficult to introduce later.

## 19. Candidate Eligibility Is Revocable

A candidate roster must not be considered permanently correct simply because it was generated earlier.

Weave remains authoritative for student status.

Design candidate eligibility so it can be:

* versioned;
* refreshed;
* revoked.

Do not automatically destroy an already-running candidate attempt when eligibility changes without an explicit policy/admin decision.

## 20. PINs and Passwords Are Hashed

Candidate examination PINs and password-like credentials must be stored using an appropriate password hashing mechanism.

Do not encrypt passwords/PINs merely so they can be recovered.

Exam content is different: retrievable sensitive content may require encryption.

Hashing and encryption solve different problems.

## 21. Do Not Invent Cryptography

Never create custom encryption algorithms, encoding schemes, or cryptographic protocols.

When encryption is implemented, use established libraries and authenticated encryption.

Keep encryption/key management behind a dedicated abstraction.

Do not scatter encryption/decryption logic throughout repositories and route handlers.

## 22. Audit Sensitive Examination Actions

Important exam administration actions must eventually be auditable.

Examples include:

* question creation/editing;
* exam submission;
* exam sealing;
* activation;
* closure;
* PIN regeneration;
* candidate revocation;
* attempt termination;
* attempt submission;
* result synchronization.

Do not log question text, correct answers, credentials, encryption keys, or other sensitive payloads into audit logs.

## 23. Cross-System Operations Must Be Idempotent

Synchronization and result ingestion must be safe to retry.

Never assume an HTTP request executed exactly once.

Use stable identifiers and database constraints so duplicate network delivery cannot create duplicate academic results or duplicate state transitions.

## 24. Do Not Hold Database Transactions Across Network Calls

Avoid:

BEGIN DATABASE TRANSACTION
→ call Weave over HTTP
→ wait
→ commit

External network calls should not keep local database transactions open.

Persist local state first where appropriate, then synchronize asynchronously.

## 25. Background Workers Must Not Own Business Rules

Workers orchestrate background execution.

They should call the same domain/application services used elsewhere rather than reimplementing exam rules independently.

Workers may handle:

* synchronization;
* result upload;
* retries;
* maintenance;
* scheduled reconciliation.

Business invariants remain in shared service/domain logic.

## 26. Keep Errors Domain-Specific

Prefer domain exceptions such as:

* ExamNotFound;
* ExamAlreadySealed;
* CandidateNotEligible;
* InvalidExamPin;
* AttemptAlreadySubmitted;
* AttemptExpired;
* QuestionPoolInsufficient.

Translate them centrally into API responses.

Avoid duplicating arbitrary `HTTPException` business-rule logic throughout route handlers.

## 27. Avoid Premature Distributed-System Complexity

Do not introduce technology merely because it may be useful at large scale.

Do NOT automatically add:

* Kafka;
* Kubernetes;
* microservices;
* distributed event buses;
* multiple databases;
* elaborate distributed locks.

Begin with:

* FastAPI;
* PostgreSQL;
* Redis where justified;
* background workers;
* Nginx;
* Docker.

Scale based on measured requirements.

## 28. Design for Thousands of Candidates, Benchmark Before Claiming Capacity

The system is expected to eventually support schools with thousands of candidates.

However, do not guess capacity.

Performance-sensitive development must eventually be validated with load tests covering:

* login bursts;
* attempt creation;
* question retrieval;
* answer checkpointing;
* reconnection/resume;
* submission bursts;
* scoring;
* result synchronization.

Optimize based on evidence.

## 29. Keep Network Boundaries Explicit

The expected architecture is:

Remote Teacher/Admin
→ secure tunnel
→ local CBT application

Student Computers
→ school LAN
→ local CBT application

CBT
↔ authenticated Weave APIs

Do not expose:

* PostgreSQL;
* Redis;
* internal worker interfaces;

to student machines or the public internet.

## 30. Respect School Ownership

The architecture intentionally allows schools to control their exam infrastructure.

Do not introduce features that silently grant the Weave operator:

* SSH access;
* arbitrary command execution;
* direct database access;
* filesystem access.

Remote support/access must be explicit and intentionally designed if introduced later.

## 31. Inspect Before Editing

Before modifying a domain:

1. inspect its current implementation;
2. inspect related models/schemas/routes/services/repositories;
3. inspect tests;
4. understand current invariants;
5. determine downstream callers;
6. then modify.

Do not make blind repository-wide refactors.

## 32. Keep Changes Focused

Do not rewrite unrelated modules simply because a different structure is preferred.

When implementing a feature:

* touch only necessary domains;
* preserve established conventions unless they create a real architectural problem;
* avoid dead code;
* remove replaced code when the migration is intentionally complete.

## 33. Database Initialization and Schema Changes

Fresh installations create the current schema from the complete model registry
through `app.core.database_bootstrap`, including exam contributor triggers.
API and worker startup must initialize or validate the database before work begins.

Automatic creation is not an upgrade mechanism. Do not change existing school
tables, discard data, or attempt partial schema repairs during startup. Model
changes for existing installations require an explicit, reviewed data-preserving
upgrade procedure and validation against a disposable PostgreSQL database.

## 34. Tests Are Part of the Implementation

Relevant domain behavior must have tests.

Especially test invariants involving:

* authorization;
* candidate eligibility;
* duplicate attempts;
* answer updates;
* resume behavior;
* sealing/versioning;
* submission idempotency;
* scoring;
* synchronization.

Do not remove useful tests to make CI green.

## 35. Before Completing Any Task

Before reporting completion:

* inspect the resulting diff;
* remove debug code;
* remove dead imports;
* run formatting/lint;
* run relevant tests;
* run database bootstrap checks where schema changed;
* report what was actually validated.

Never claim tests passed unless they were run successfully.

## 36. Do Not Merge Unless Explicitly Asked

Do not merge branches, push to production, alter remote infrastructure, or perform destructive deployment operations unless the user explicitly requests it.

## Core Principle

Always preserve this separation:

WEAVE
= identity + academic authority

LOCAL CBT
= examination content + examination execution

The integration should make the two systems feel like one product without allowing either system to own responsibilities that belong to the other.
