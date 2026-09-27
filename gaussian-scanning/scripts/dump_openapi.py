#!/usr/bin/env python3
"""Write the API's OpenAPI schema to app/openapi.json (input to the frontend's
`npm run gen:api`, which generates src/api/schema.d.ts)."""
import json
from pathlib import Path

from app.server.main import app

out = Path(__file__).resolve().parents[1] / "app" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")
