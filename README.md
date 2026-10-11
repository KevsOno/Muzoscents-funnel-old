---
title: Kevs Digital bOS
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Kevs Digital bOS backend API
---

# Kevs Digital bOS

Backend API for the Kevs Digital bOS platform.

Multi-tenant inventory, POS, accounting, HR, procurement, and storefront infrastructure.

## Endpoints

- `/health` — service health check
- `/auth/*` — authentication
- `/inventory/*` — inventory management
- `/store/{slug}` — public storefront routing
- `/public/*` — public data endpoints

## Stack

- FastAPI
- Supabase (PostgreSQL)
- Docker on Hugging Face Spaces




