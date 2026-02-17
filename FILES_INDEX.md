# Project File Index

This file provides a concise description of the repository structure and the purpose of important files and folders.

- **manage.py**: Django project CLI entrypoint for development tasks and management commands.
- **requirements.txt**: Python dependencies for the project environment.
- **sample_faculty.csv / sample_students.csv**: Example CSVs used for bulk import testing and format reference.
- **SQL_INJECTION_PREVENTION_DOCUMENTATION.txt**: Comprehensive security documentation covering SQL injection prevention, error handling, and database security.
- **train_sentiment.ipynb**: Jupyter notebook used to train or experiment with the sentiment model.

- **api/**: Django application implementing the REST API.
  - `authentication.py`, `throttles.py`, `middleware.py`: request handling and protection logic.
  - `views.py`, `urls.py`, `serializers/`, `models/`: core API endpoints, serializers, and models for students, faculty, forms, and audit logs.
  - `management/commands/check_security.py`: custom security check management command.

- **backend/**: Secondary backend area for AI engine and model-serving components.
  - `ai_engine/processors.py`, `services.py`: model inference and processing logic.
  - `models/sentiment_model_final/`: serialized sentiment model artifacts used in production.

- **config/**: Django configuration package for the `sfme` deployment.
  - `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`: environment and WSGI/ASGI configuration.

- **feedback/**: App-level models and views that integrate with the core feedback collection flow.

- **blockchain/**: Smart contract integration utilities or scripts used for integrity verification (if present).

- **data/**: Data sources and datasets used during development (e.g., `feedback_dataset.csv`).

- **database/**: Local database helpers or SQL migration assets (if present).

- **frontend_vite/** and **upang-sfme/**: Frontend application(s) using Vite + React. Key files:
  - `frontend_vite/upang-sfme/package.json`: frontend dependencies and scripts
  - `src/` and `public/`: frontend source, components, pages, assets.

- **log/** and **logs/**: Directories for runtime logs and security/audit logs. See `logs/security.log` referenced in security documentation.

- **myenv/**: Local virtual environment (do not commit to source control). Contains Python runtime and installed packages.

- **sentiment_model_final/**: Finalized sentiment model artifacts (tokenizer, model weights); used by the AI inference service.

- **sfme/**: Django project package (top-level project settings and entrypoints for deployment).

Notes and recommendations:
- Use `SQL_INJECTION_PREVENTION_DOCUMENTATION.txt` for security and operational guidance.
- Keep `myenv/` out of commits; prefer `.venv` or CI-managed environments.
- For API reference, consult `api/serializers/`, `api/models/`, and `api/views.py` for endpoint and field definitions.

If you want, I can:
- Expand this into a full `README.md` section and replace the current abbreviated README.
- Generate inline docstrings across Python files.
- Create Sphinx-style docs with autodoc for the `api` and `backend` modules.

Which option would you like next?