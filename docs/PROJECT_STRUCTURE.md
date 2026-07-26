# Project folder structure

```text
.
├── apps/                       # Project business applications
│   ├── accounts/               # Created in stage 3
│   ├── employees/              # Created in stage 3
│   ├── groups/                 # Created in stage 3
│   ├── sales/                  # Created in stage 3
│   ├── imports/                # Created in stage 3
│   ├── statistics/             # Created in stage 3
│   ├── telegram_bot/           # Created in stage 3
│   └── common/                 # Created in stage 3
├── config/                     # Django project configuration and entry points
├── docs/                       # Architecture and implementation documentation
├── static/                     # Versioned static assets, when required
├── media/                      # Runtime uploaded files; excluded from Git later
├── tests/                      # Project-wide automated tests
│   ├── unit/                   # Domain/application-level tests
│   └── integration/            # Database and adapter integration tests
├── manage.py                   # Django management command entry point
├── pyproject.toml              # Packaging, dependencies, and tooling settings
└── README.md                   # Project entry documentation
```

## Application internal convention

Every business app added under `apps/` will use this layout when it needs the
relevant responsibility:

```text
apps/<application>/
├── admin.py                    # Django Admin presentation adapter
├── apps.py                     # Django application configuration
├── models.py                   # Persistence model declarations only
├── repositories/               # Repository interfaces and ORM implementations
├── services/                   # Business use-cases and transaction orchestration
├── selectors/                  # Read-only, optimized query composition (if needed)
├── api/                        # DRF serializers, views and URLs (if exposed)
├── migrations/                 # Django migration history
└── tests/                      # Tests belonging to this application
```

Not every app will have every directory. Directories are created only when a
real responsibility exists; this prevents empty abstractions while preserving
Clean Architecture boundaries.

## Boundary rules

- `models.py` holds persistence structure and simple data invariants only.
- `repositories/` isolates ORM query and write details behind explicit
  repository contracts.
- `services/` is the only location for business workflows and calculations.
- HTTP views, Django Admin actions, management commands, and Aiogram handlers
  are presentation adapters: they validate input, call a service, and render a
  response. They never query ORM models directly.
- `common/` may contain genuinely shared technical primitives only. It must not
  become a catch-all place for unrelated business logic.
- `static/` is committed only for source assets. `media/` holds runtime uploads
  and will be ignored by Git when upload support is introduced.
