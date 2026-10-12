# Weave CBT

Database setup and handoff cleanup: [Database initialization](docs/database-initialization.md).

Weave CBT is a **school-hosted Computer-Based Testing runtime** that extends the Weave school-management platform.

The CBT application runs entirely on infrastructure controlled by the school and is accessed by teachers, administrators, and students through the school's local network.

Weave remains the authoritative cloud platform for identity, school membership, academics, enrollment, assessment configuration, and final academic results.

The local CBT runtime owns the complete examination lifecycle.

---

# Core Architecture

The system follows one simple rule:

```text
WEAVE
=
identity + academics + final academic results

LOCAL CBT
=
everything examination-related
```

The systems communicate only through authenticated HTTP APIs.

Weave never connects directly to the school's PostgreSQL database.

The local CBT server never connects directly to Weave's database.

---

# System Overview

```text
                    WEAVE CLOUD
                         │
                         │
           ┌─────────────┼─────────────┐
           │             │             │
       Staff Auth     Academics     Students
           │             │             │
           └─────────────┬─────────────┘
                         │
                 Authenticated HTTPS
                         │
                         ▼
                  LOCAL CBT SERVER
                         │
           ┌─────────────┼─────────────┐
           │             │             │
       Questions       Exams       Candidates
           │             │             │
           └─────────────┼─────────────┘
                         │
                      Attempts
                         │
                       Answers
                         │
                       Scoring
                         │
                       Results
                         │
                  batched score sync
                         │
                         ▼
                    WEAVE CLOUD
```

Student examination traffic remains inside the school network.

An active examination must not require continuous connectivity to Weave.

---

# Product Boundary

## Weave Owns

Weave remains the source of truth for:

* tenants/schools;
* administrators;
* teachers;
* students;
* teacher memberships;
* teacher class-subject assignments;
* student enrollment;
* classes;
* subjects;
* academic sessions;
* academic terms;
* assessment schemes;
* assessment components;
* grading configuration;
* final academic results;
* CBT subscription eligibility.

The CBT application consumes only the subset of this information required for examination execution.

---

## Local CBT Owns

The school-owned CBT runtime is authoritative for:

* question banks;
* questions;
* answer options;
* correct answers;
* examination definitions;
* examination versions;
* examination schedules;
* examination candidate lists;
* candidate examination credentials;
* candidate attempts;
* question allocation;
* candidate answers;
* examination timers;
* submission;
* local scoring;
* raw examination results;
* examination audit records;
* synchronization state.

Exam questions, answer keys, attempts, and candidate answers do not need to be uploaded to Weave.

The school retains control of its examination data.

---

# Deployment Model

The CBT package is distributed as a Docker-based application.

The same Linux-container stack should run regardless of the physical host operating system.

Supported host environments include:

```text
Windows
    ↓
Docker Desktop + WSL2
    ↓
Linux containers


macOS
    ↓
Docker Desktop
    ↓
Linux containers


Linux
    ↓
Docker Engine
    ↓
Linux containers
```

The application itself must not contain Windows-, macOS-, or Linux-specific business logic.

Host-specific concerns belong to Docker and installation tooling.

---

# Runtime Components

A production CBT installation is expected to contain:

```text
School LAN
    │
    ▼
Nginx
├── React frontend
└── /api
      ↓
FastAPI workers
      │
      ├── PostgreSQL
      ├── Redis
      └── Taskiq workers
```

Core components:

* **Nginx** — local reverse proxy and frontend delivery;
* **React frontend** — teacher, admin, and candidate interfaces;
* **FastAPI** — local application backend;
* **PostgreSQL** — durable examination source of truth;
* **Redis** — caching, coordination, rate limiting, and worker infrastructure;
* **Taskiq workers** — background synchronization and maintenance.

PostgreSQL is authoritative.

Redis is never the only copy of examination-critical data.

---

# Local Network Access

Teachers, administrators, and students access the CBT application through the school LAN.

A school may expose the server locally using an address such as:

```text
http://192.168.1.50
```

or preferably a friendly local hostname such as:

```text
https://cbt.school.local
```

The CBT server does not need to be publicly accessible from the internet.

Teachers and administrators are expected to perform examination-authoring and management activities while connected to the school's network.

This is an intentional security boundary.

---

# Installation and Pairing

A CBT installation must first be associated with a Weave school.

Pairing occurs only during installation or explicit replacement.

The intended flow is:

```text
School admin
    ↓
Weave Admin Dashboard
    ↓
CBT
    ↓
Pair Local Server
    ↓
Weave generates short-lived setup code
    ↓
Admin enters code into local CBT
    ↓
Local CBT sends code to Weave
    ↓
Weave validates:
- code exists
- code has not expired
- code has not been used
- school has an eligible plan
    ↓
Weave authorizes the installation
    ↓
CBT receives a long-lived installation credential
```

The temporary pairing code must not become the permanent server credential.

Once pairing succeeds, the temporary code becomes invalid.

The issued installation credential identifies exactly one school.

---

# Installation Credential

The CBT server uses its installation credential when communicating with Weave.

For example:

```text
LOCAL CBT
    ↓
authenticated Weave integration API
    ↓
WEAVE
```

The credential allows Weave to determine:

```text
which CBT installation is calling
which school owns it
whether the installation is active
whether the school's subscription allows CBT
```

The local CBT must not be trusted to submit an arbitrary tenant identifier and access another school's information.

Tenant context must be derived from the authenticated installation.

---

# Persistent Installation State

The installation credential must survive:

* container restarts;
* container replacement;
* Docker image updates;
* operating-system restart;
* machine power loss.

It must therefore not live only inside a disposable container filesystem.

Persistent installation state should be mounted into containers using Docker-managed persistent storage.

Conceptually:

```text
Persistent CBT identity storage
├── installation identifier
├── installation credential
└── local security configuration
```

Deleting or replacing application containers must not require the school to pair the installation again.

A complete loss of the host's persistent data may require explicit recovery or re-pairing.

---

# Staff Authentication

Teachers and administrators authenticate using their existing Weave credentials.

The local CBT does not maintain a second permanent password system for staff.

The flow is:

```text
Teacher/Admin
    ↓
opens local CBT
    ↓
enters Weave credentials
    ↓
Local CBT forwards login request to Weave
    ↓
Weave authenticates user
    ↓
Weave verifies membership in THIS school
    ↓
Weave returns local CBT authorization context
    ↓
Local CBT discards the password
    ↓
Local CBT creates its own local session
```

Weave credentials must never be:

* stored in local PostgreSQL;
* stored in Redis;
* written to logs;
* written to audit records;
* persisted to disk;
* included in error telemetry.

They exist only for the authentication request.

---

# Multi-School Teachers

Weave supports teachers belonging to multiple schools.

The CBT installation already belongs to exactly one school.

Therefore no school selector is required on the CBT login screen.

Example:

```text
Teacher Taiwo

Memberships:
├── Greenfield College
├── Bluebell Academy
└── Royal School
```

If Taiwo logs into Greenfield's CBT server:

```text
Greenfield CBT
    ↓
Weave authentication
    ↓
Weave checks Taiwo's GREENFIELD membership
```

Only Greenfield-specific authority is returned.

A different CBT installation belonging to Bluebell would resolve Taiwo's Bluebell membership instead.

---

# Staff Authorization

Successful authentication does not automatically give unrestricted CBT access.

Weave remains authoritative for teacher assignments.

For example:

```text
Teacher:
Taiwo

Assignments:
JSS2 Mathematics
JSS3 Mathematics
```

The local CBT may therefore allow:

```text
JSS2 Mathematics question authoring
JSS3 Mathematics question authoring
```

but reject:

```text
SS3 Chemistry question authoring
```

A teacher must never gain examination-authoring authority solely because:

```text
role == teacher
```

Class-subject authority must also be validated.

Administrators receive the local administrative authority required to manage examination workflows.

---

# Local Staff Sessions

Once Weave authenticates a staff member, CBT creates its own local authentication session.

The session is independent of the temporary Weave authentication response.

The local session may use:

* a short-lived access token;
* a longer-lived refresh token;
* local revocation/session tracking.

Conceptually:

```text
Weave login
    ↓
authenticated staff identity
    ↓
Local CBT session
    ↓
Local access token
+
Local refresh token
```

Subsequent CBT activity occurs entirely locally.

The CBT must not repeatedly send staff passwords to Weave when local access tokens expire.

Local refresh behavior must happen locally.

---

# Offline Staff Behaviour

A new staff login normally requires connectivity to Weave because Weave remains the identity authority.

However, once a valid local CBT session exists:

```text
Weave unavailable
        ↓
existing local session remains usable
```

An internet outage must not invalidate active local examination operations.

---

# Academic Projection

The CBT runtime stores only the academic information required to run examinations.

This may include local projections of:

* classes;
* subjects;
* sessions;
* terms;
* assessment components;
* teacher assignments.

The CBT must not recreate Weave's complete academic-management system.

These records exist only as references required by local exam domains.

---

# Assessment Configuration

The CBT must never hardcode assessment types such as:

```text
Test
Exam
Quiz
CA
Midterm
```

Instead, assessment configuration comes from Weave.

Example:

```text
Greenfield College

First Term

Assessment components:
├── Test          30 marks
└── Examination   70 marks
```

CBT synchronizes these definitions and stores the Weave identifiers locally.

A local exam therefore references:

```text
Weave session ID
Weave term ID
Weave subject ID
Weave class ID
Weave assessment-component ID
```

When the local result is later synchronized, Weave immediately knows where that score belongs.

---

# Academic Snapshots and Versioning

Changes in Weave must not silently mutate already finalized examinations.

If an examination is created using:

```text
Examination = 70 marks
```

and the school's configuration later becomes:

```text
Examination = 80 marks
```

the existing sealed examination must preserve the original configuration it was created with.

Local examinations therefore preserve the relevant academic snapshot/version required for historical correctness.

---

# Question Authoring

All question authoring occurs locally.

The teacher must be connected to the school's CBT network.

Questions are stored only in the school's local PostgreSQL database.

Question data includes:

* question bank;
* subject;
* class;
* question text;
* answer options;
* correct answer;
* question type;
* relevant metadata.

Weave does not need to receive the question content.

---

# Examination Lifecycle

A typical exam lifecycle is:

```text
DRAFT
    ↓
Teacher authors/configures
    ↓
SUBMITTED
    ↓
Admin reviews
    ↓
SEALED
    ↓
Scheduled
    ↓
ACTIVE
    ↓
CLOSED
```

Exact lifecycle names may evolve, but the core authority remains:

```text
Teacher
= authors

Administrator
= final examination authority
```

Teachers must not seal or activate examinations unless product requirements explicitly change.

---

# Examination Immutability

Once an examination is finalized/sealed, question content must not silently change.

If corrections are required, they should happen through an explicit revision/version lifecycle.

Candidates participating in one exam version must not unknowingly receive different question revisions.

---

# Candidate Synchronization

Students are not authenticated against Weave during an active examination.

Before an examination, the CBT server fetches the required eligible students from Weave.

Example:

```text
CBT
    ↓
Weave integration API
    ↓
eligible students for:
- class
- session
- term
- exam context
```

CBT stores the candidate list locally.

Candidate information should contain only what is necessary, for example:

* Weave student identifier;
* admission number;
* name;
* class;
* enrollment/eligibility status.

The CBT must never copy student Weave passwords.

---

# Candidate Authentication

Candidate examination access is owned locally by CBT.

The preferred model is:

```text
Admission Number
+
random per-exam PIN
```

Example:

```text
Admission Number:
GRN/2026/0042

Exam PIN:
482917
```

Candidate PINs must:

* be generated using cryptographically secure randomness;
* belong to a specific examination;
* be stored only as password hashes;
* be rate-limited against repeated guessing;
* be revocable/regenerable by authorized administrators.

Predictable credentials such as:

```text
username = admission number
password = lowercase admission number
```

must not be used.

Admission numbers are identifiers, not secrets.

---

# Candidate Sessions

Once a candidate is authenticated, CBT creates a local candidate session tied to:

```text
candidate
+
exam
+
attempt
```

The candidate frontend must never be trusted to choose arbitrary:

* student IDs;
* examination IDs;
* attempt IDs.

The backend derives these from the authenticated candidate session.

---

# Attempt Ownership

An attempt belongs to:

```text
candidate + examination
```

not to a particular computer.

If a candidate's computer fails:

```text
Candidate moves to another computer
    ↓
logs in again
    ↓
CBT discovers existing unfinished attempt
    ↓
attempt resumes
```

The candidate must not silently receive another attempt simply because their device changed.

---

# Question Allocation

Question randomization/allocation is attempt-specific.

Allocation must be generated once and persisted.

An attempt should preserve:

* selected question IDs;
* question order;
* option order where applicable;
* exam version.

The CBT must never reshuffle an examination every time the browser requests the next question.

This is necessary for recovery after:

* browser failure;
* power interruption;
* computer replacement;
* network interruption.

---

# Answer Persistence

Candidate answers are durably stored in local PostgreSQL.

Critical answer state must never exist only in:

* frontend memory;
* Redis;
* FastAPI process memory.

The primary path is:

```text
Candidate
    ↓
FastAPI
    ↓
PostgreSQL transaction
    ↓
commit
```

Browser-side IndexedDB/local persistence may be used as an additional recovery layer but is never authoritative.

---

# Scoring

Scoring is server-authoritative.

Correct answers must never be trusted to or scored by the candidate frontend.

The flow is:

```text
Candidate submits
    ↓
Local FastAPI
    ↓
stored candidate answers
+
local authoritative answer key
    ↓
score calculation
    ↓
LocalResult
```

The candidate may see the resulting score immediately if the examination configuration permits it.

---

# Result Synchronization

After examination scoring, results are stored locally first.

Example:

```text
LocalResult

student
exam
score
maximum score
sync status
```

A background worker sends pending scores to Weave in batches.

```text
LOCAL CBT
    ↓
score batch
    ↓
WEAVE
```

Weave then applies the score to its academic result system using the referenced:

* student;
* subject;
* term;
* session;
* assessment component.

---

# Result Synchronization Reliability

Score synchronization must be idempotent.

Every result sent to Weave must have a stable unique integration reference.

If:

```text
CBT sends result
    ↓
Weave saves result
    ↓
network fails before CBT receives response
```

CBT may safely retry.

Weave must recognize that the result was already processed rather than creating a duplicate.

---

# Offline Examination Requirement

An active examination must remain functional when:

```text
Internet unavailable
Weave unavailable
```

provided that:

```text
Local server is available
PostgreSQL is available
School LAN is available
Required candidates/configuration were prepared locally
```

During an outage, CBT must continue supporting:

* candidate login;
* attempt creation/resume;
* question delivery;
* answer persistence;
* timing;
* submission;
* scoring.

Only cloud-dependent operations should wait, such as:

* new staff authentication;
* academic synchronization;
* new candidate synchronization;
* score upload.

---

# PostgreSQL

PostgreSQL is the durable source of truth for the local CBT runtime.

Critical examination state includes:

* question banks;
* questions;
* exams;
* candidate eligibility;
* attempts;
* question allocation;
* answers;
* raw results;
* audit events;
* synchronization state.

Database correctness must rely on appropriate:

* foreign keys;
* unique constraints;
* indexes;
* transactions;
* locking/concurrency controls.

Important invariants should be enforced at the database layer whenever possible.

---

# Redis

Redis is a performance and coordination layer.

Redis may be used for:

* caching;
* rate limiting;
* worker infrastructure;
* temporary coordination;
* runtime metadata.

Redis must never contain the only copy of:

* candidate answers;
* examination attempts;
* results;
* question allocations.

Rule:

```text
Redis = speed

PostgreSQL = truth
```

---

# Workers

Background workers should orchestrate asynchronous operations.

Expected worker responsibilities include:

```text
academics.py
    academic/reference synchronization

results.py
    pending score synchronization

maintenance.py
    session cleanup
    expired records
    housekeeping
```

Workers must not become independent owners of business rules.

They should call the same domain services used elsewhere.

---

# Weave Integration Layer

All HTTP communication with Weave must stay inside:

```text
app/integrations/weave/
```

Recommended structure:

```text
integrations/weave/
├── client.py
├── installation.py
├── auth.py
├── academics.py
├── results.py
├── schemas.py
└── exceptions.py
```

Responsibilities:

### `client.py`

* shared asynchronous HTTP client;
* base URL;
* timeouts;
* installation authentication;
* transport-level failures.

### `installation.py`

* initial CBT pairing;
* installation activation/status.

### `auth.py`

* teacher/admin credential verification;
* school membership validation;
* staff authorization context.

### `academics.py`

* academic configuration;
* assessment components;
* teacher assignments;
* candidate/student synchronization.

### `results.py`

* score batch synchronization.

Domain services must never scatter arbitrary direct HTTP calls to Weave.

---

# Local Backend Domains

The lightweight backend architecture is:

```text
app/domains/

auth/
academics/
questions/
exams/
candidates/
attempts/
results/
audit/
```

---

# `auth`

Owns:

* local staff access/refresh tokens;
* local session records;
* token rotation/revocation;
* current authenticated staff dependencies.

It does not own Weave password verification.

---

# `academics`

Owns local projections of:

* classes;
* subjects;
* sessions;
* terms;
* assessment components;
* teacher assignments.

It does not become another academic-management system.

---

# `questions`

Owns:

* question banks;
* questions;
* options;
* correct answers;
* question metadata;
* teacher authoring authorization.

All data remains local.

---

# `exams`

Owns:

* exam definition;
* class/subject association;
* assessment component association;
* exam lifecycle;
* schedule;
* duration;
* sealing;
* versioning;
* activation;
* closure.

Scheduling remains part of the exam domain instead of becoming a separate service.

---

# `candidates`

Owns:

* synchronized student projections;
* examination eligibility;
* candidate rosters;
* exam PIN generation;
* PIN verification;
* candidate login.

---

# `attempts`

Owns:

* candidate attempt creation;
* duplicate-attempt prevention;
* question allocation;
* answer persistence;
* timing;
* resume/recovery;
* submission.

---

# `results`

Owns:

* local scoring output;
* raw examination scores;
* result synchronization status;
* result retry/idempotency metadata.

CBT does not calculate final academic grades.

---

# `audit`

Owns security-sensitive and exam-sensitive event history.

Examples:

* question created;
* exam submitted;
* exam sealed;
* exam activated;
* candidate login failure;
* attempt started;
* attempt resumed;
* attempt force-submitted;
* result synchronized.

Audit records must not contain:

* staff passwords;
* candidate PINs;
* access tokens;
* refresh tokens;
* full question content;
* correct answers.

---

# Route → Service → Repository

The backend follows:

```text
Route
  ↓
Service
  ↓
Repository
  ↓
PostgreSQL
```

Routes should remain thin.

Routes handle:

* HTTP concerns;
* input validation;
* authentication dependencies;
* calling services;
* response serialization.

Services handle business rules.

Repositories handle database access.

---

# Container Persistence

Application containers are disposable.

School data is not.

The architecture must ensure:

```text
Delete FastAPI container
→ data remains

Delete worker container
→ data remains

Delete PostgreSQL container
→ PostgreSQL volume remains

Pull new application image
→ data remains

Restart machine
→ data remains
```

Persistent Docker volumes should store durable local state.

At minimum:

```text
weave_cbt_postgres_data
weave_cbt_identity
```

Redis persistence may be configured separately, but Redis remains non-authoritative.

---

# Backups

Docker volumes are not backups.

Schools must be able to recover from:

* disk failure;
* operating-system reinstall;
* laptop theft;
* Docker reset;
* accidental volume deletion;
* hardware destruction.

The CBT deployment should therefore support automated PostgreSQL backups to a school-controlled location.

Examples:

```text
Windows:
C:\WeaveCBT\Backups

macOS:
/Users/Shared/WeaveCBT/Backups

Linux:
/var/backups/weave-cbt
```

Inside containers, the application should use one consistent mounted path such as:

```text
/backups
```

The school may additionally copy backups to:

* external storage;
* NAS;
* another local machine.

Backups do not need to be uploaded to Weave.

---

# Power Failure and Crash Recovery

Committed examination data must survive abnormal shutdown.

PostgreSQL durability must not be weakened merely for performance benchmarks.

The application should rely on normal PostgreSQL crash-recovery guarantees and ensure important candidate operations are committed transactionally.

Schools running real examinations should use appropriate power protection such as:

* UPS;
* inverter;
* generator where available.

A UPS reduces the chance of abrupt server loss and allows clean failover/shutdown during electricity interruption.

---

# Availability vs Durability

These are different concerns.

```text
Persistent volume
= survives container replacement

PostgreSQL durability
= survives crashes

Backups
= survives disk/server loss

Redundant hardware
= survives machine failure without long downtime
```

A single local machine can provide strong durability but cannot remain available if the hardware itself dies.

Large schools may later deploy a standby server or PostgreSQL replication strategy.

That is infrastructure scaling and is not required for the initial application architecture.

---

# Local Scaling

The CBT server may run multiple FastAPI worker processes behind Nginx.

Example:

```text
Nginx
   ↓
FastAPI worker 1
FastAPI worker 2
FastAPI worker 3
FastAPI worker 4
   ↓
shared PostgreSQL
shared Redis
```

The exact worker count must be based on:

* CPU cores;
* RAM;
* PostgreSQL capacity;
* disk performance;
* expected candidate load.

Do not assume that more workers automatically provide better performance.

Load testing is required.

---

# Shared State

Multiple FastAPI workers must remain interchangeable.

Critical state must not exist only in local process memory.

Avoid patterns such as:

```python
active_attempts = {}
logged_in_users = set()
login_attempts = {}
```

for shared runtime state.

Use:

```text
PostgreSQL
= durable shared state

Redis
= temporary shared coordination/cache

Tokens
= authenticated local identity
```

This allows Nginx to route requests to any API worker.

---

# Database Connection Pools

Database pools are per application process.

Therefore:

```text
number of workers
×
pool size
```

must be considered.

Very large pool settings across many workers can overwhelm PostgreSQL on a school machine.

Connection-pool values must therefore be tuned during load testing rather than copied from cloud infrastructure defaults.

---

# Network Capacity

Candidate capacity is not only an application-server problem.

Large deployments also depend on:

* school LAN capacity;
* Ethernet backbone;
* managed switches;
* wireless access points;
* DHCP capacity;
* server NIC speed;
* SSD performance.

The CBT server should preferably use a wired network connection.

Claims such as:

```text
supports 5,000 students
```

must only be made after testing both application and network infrastructure.

---

# Cross-Platform Images

Weave CBT should publish Linux container images for at least:

```text
linux/amd64
linux/arm64
```

This allows the same release to work across:

* common Windows/Intel/AMD machines;
* Linux servers;
* Intel Macs;
* Apple Silicon Macs.

The application should not require separate Windows/macOS/Linux builds.

---

# Security Principles

The initial security model follows these rules:

1. Weave remains the source of truth for staff identity.
2. Local CBT never stores staff Weave passwords.
3. Local CBT creates and controls its own staff sessions after authentication.
4. Teacher authorization includes class-subject assignment.
5. Students authenticate locally for individual examinations.
6. Candidate PINs are random and hashed.
7. Candidate sessions are bound to candidate + exam + attempt.
8. Correct answers never become authoritative on the frontend.
9. Server-side scoring is authoritative.
10. Sensitive credentials must never appear in logs.
11. Weave integration credentials must be protected and persistent.
12. Student answers and exam content remain school-local.
13. Weave receives only the academic information it needs.

---

# Integration Boundary

The allowed integration surface is intentionally small.

## Weave → CBT

```text
staff authentication result
staff school membership
teacher class-subject authority
academic configuration
assessment components
eligible student records
```

## CBT → Weave

```text
result batches
installation status where required
```

Question content, correct answers, attempts, and student answer data are not part of the normal integration contract.

---

# Failure Model

The intended behavior is:

```text
Weave unavailable
→ active exams continue

Internet unavailable
→ active exams continue

Redis unavailable
→ CBT should degrade where possible

PostgreSQL unavailable
→ CBT cannot safely operate

API container replaced
→ data survives

server reboot
→ data survives

machine/disk destroyed
→ restore from backup

hardware dies during exam
→ downtime unless standby hardware exists
```

---

# Repository Structure

Recommended backend structure:

```text
backend/
└── app/
    ├── core/
    │   ├── settings.py
    │   ├── database.py
    │   ├── redis.py
    │   ├── security.py
    │   ├── exceptions.py
    │   └── logging.py
    │
    ├── domains/
    │   ├── auth/
    │   ├── academics/
    │   ├── questions/
    │   ├── exams/
    │   ├── candidates/
    │   ├── attempts/
    │   ├── results/
    │   └── audit/
    │
    ├── integrations/
    │   └── weave/
    │       ├── client.py
    │       ├── installation.py
    │       ├── auth.py
    │       ├── academics.py
    │       ├── results.py
    │       ├── schemas.py
    │       └── exceptions.py
    │
    ├── workers/
    │   ├── broker.py
    │   ├── academics.py
    │   ├── results.py
    │   └── maintenance.py
    │
    └── main.py
```

Expected deployment files may eventually include:

```text
docker/
├── backend.Dockerfile
├── frontend.Dockerfile
└── nginx.conf

compose.yaml
.env.example
```

---

# Development Principles

Development should proceed incrementally:

```text
1. Core settings/database/Redis/security
2. Database base models and automatic first-install bootstrap
3. Installation pairing
4. Local staff authentication/session system
5. Academic projections
6. Question banks/questions
7. Exam lifecycle
8. Candidate synchronization
9. Candidate authentication
10. Attempts and answer persistence
11. Local scoring
12. Result synchronization
13. Audit
14. Docker/Nginx/persistence
15. Resilience testing
16. Load testing
```

Avoid premature additions such as:

* Kubernetes;
* Kafka;
* RabbitMQ;
* microservices;
* public CBT servers;
* tunneling infrastructure;
* cloud-hosted question banks;
* duplicated Weave domains.

Start with:

```text
FastAPI
PostgreSQL
Redis
Taskiq
Nginx
Docker
```

and scale only when measurements demonstrate a need.

---

# Core Principle

Every engineering decision in this repository should preserve the following:

```text
WEAVE
=
identity + academic authority

LOCAL CBT
=
exam content + exam execution
```

And:

```text
The school owns its examination environment.

Weave coordinates identity and academics.

The local CBT runs the exam.
```
