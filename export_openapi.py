import json
from app.main import app

def export():
    openapi_schema = app.openapi()
    with open("openapi.json", "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
    print("Successfully exported openapi.json (OpenAPI version:", openapi_schema.get("openapi"), ")")

if __name__ == "__main__":
    export()
