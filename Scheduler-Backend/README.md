---
title: CP SAT Timetable Scheduler
emoji: 🗓️
colorFrom: indigo
colorTo: blue
sdk: docker
app_file: app.py
pinned: false
---

# PAU Scheduler CPSAT Documentation

This document explains the most important files, the folder structure, and the end to end processing flow used to generate timetables.

## Repository layout

1. `Scheduler-Backend`
   Contains API routes, data transformation logic, and scheduling engines.

2. `Scheduler-Frontend`
   Contains the React user interface used for upload, generation, and download.

## Backend file structure and purpose

1. `app.py`
   Main Flask entry point. Registers routes and starts the backend service.

2. `input_data_api.py`
   Receives uploaded Excel data and stores normalized JSON files for scheduling.

3. `transformer_api.py`
   Runs input transformation endpoints and maps raw spreadsheet data to internal entities.

4. `constraints_api.py`
   Exposes constraint validation and reporting endpoints.

5. `output_data_api.py`
   Exposes endpoints for timetable retrieval and download.

6. `cp_sat_scheduler.py`
   Core scheduling engine powered by Google OR Tools CP SAT.

7. `constraints.py`
   Defines rule checks such as lecturer clashes, room conflicts, and allocation limits.

8. `transformer.py`
   Converts uploaded source data into objects used by scheduling logic.

9. `input_data.py`
   Handles parsing and intermediate storage of uploaded source content.

10. `output_data.py`
    Shapes final scheduling results for frontend rendering and export.

11. `export_service.py`
    Produces export artifacts such as spreadsheet outputs.

12. `verify_output.py`
    Validates generated output and produces violation summaries.

13. `data/`
    Stores runtime JSON inputs, generated timetable data, and verification outputs.

14. `entitities/`
    Defines core domain classes such as `course`, `faculty`, `room`, `student_group`, and `time_slot`.

## Frontend file structure and purpose

1. `src/App.js`
   Root React component that mounts the timetable workflow.

2. `src/components/TimetableGenerator.js`
   Main orchestration component for upload, generation, progress updates, and result state.

3. `src/components/FileUpload.js`
   Handles file selection, validation, and upload triggering.

4. `src/components/TimetableResults.js`
   Renders generated timetable grids and result navigation.

5. `src/services/api.js`
   Central HTTP client layer for backend calls.

6. `src/setupProxy.js`
   Development proxy mapping from frontend origin to backend API.

## End to end process flow

1. User uploads an Excel file in the frontend.

2. Frontend sends the file through `api.js` to backend upload endpoints.

3. Backend input modules parse sheets and write normalized JSON in `data/`.

4. Transformer modules map normalized records into scheduling entities.

5. Constraint modules build rule checks and feasibility filters.

6. CP SAT scheduler builds the optimization model and solves timetable assignments.

7. Output modules convert solver results into frontend friendly structures.

8. Verification modules compute constraint violations and summary reports.

9. Frontend fetches generated timetables, displays them, and allows export.

## Practical mapping from endpoint to code

1. Upload request enters API route files and reaches `input_data_api.py` plus `input_data.py`.

2. Generation request calls transformation and constraints layers, then `cp_sat_scheduler.py`.

3. Result request calls `output_data_api.py` and `output_data.py`.

4. Export request calls `export_service.py`.

## How to read this codebase quickly

1. Start with `app.py` to see route registration and service startup.

2. Continue with `input_data_api.py`, `transformer_api.py`, `constraints_api.py`, and `output_data_api.py` to understand HTTP boundaries.

3. Read `cp_sat_scheduler.py` for optimization variables, constraints, and objective.

4. Review `constraints.py` and `verify_output.py` for rule definitions and quality checks.

5. Open `TimetableGenerator.js` and `api.js` in the frontend to follow user actions to backend calls.

## Hugging Face Space deployment and sync

1. Space repository URL
   `https://huggingface.co/spaces/PAU-001/CP-SAT_Timetable_Scheduler`

2. Space runtime URL
   `https://pau-001-cp-sat-timetable-scheduler.hf.space`

3. Automatic sync strategy
   The workflow file `.github/workflows/sync-hf-space.yml` mirrors `Scheduler-Backend` into the Space root on each push to `main`.

4. Required GitHub secrets
   Add `HF_TOKEN` in repository secrets with write access to the Space.
   Optional `HF_SPACE_ID` can be set to the exact Space path such as `PAU-001/CP-SAT Timetable Scheduler` if your Space uses spaces or a different slug.

5. What gets synced
   Only backend files are copied, so the Space receives `app.py`, `Dockerfile`, dependencies, APIs, and data files from `Scheduler-Backend`.
   Generated export files in `output_data/Hybrid-Timetables/*.xlsx` are excluded from Space sync to satisfy Hugging Face binary push restrictions.
