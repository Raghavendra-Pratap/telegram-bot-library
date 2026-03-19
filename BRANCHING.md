# Branching and Release Flow

This repo uses a **three-tier workflow** to keep production stable while allowing rapid development.

## Branches

- `main`: Production-ready bots only (currently `name-bot`).
- `development`: All active under-development bots and shared changes.
- `feature/*`: Bot-specific or task-specific work.

## Flow

```
feature/*  -->  development  -->  main
```

## Promotion rules

- A bot stays in `development` until it is tested locally and ready.
- When ready, merge `development` into `main`.
- The server installs new dependencies **only after** they land in `main`.

## Server dependency policy

- Server installs **only `main` dependencies**.
- Dev-only bot dependencies are installed locally for testing.
