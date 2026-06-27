from supabase import create_client
import os

BUILTIN_TRACKS = [
    {
        "name": "Python Foundations",
        "level": "beginner",
        "description": "Variables, functions, OOP, async basics.",
        "checkpoints": [
            {"sequence": 1, "title": "Variables & Types", "resource_url": "https://realpython.com/python-data-types/", "xp_value": 10},
            {"sequence": 2, "title": "Functions & Scope", "resource_url": "https://realpython.com/defining-your-own-python-function/", "xp_value": 10},
            {"sequence": 3, "title": "OOP: Classes & Inheritance", "resource_url": "https://realpython.com/python3-object-oriented-programming/", "xp_value": 15},
            {"sequence": 4, "title": "Error Handling & Exceptions", "resource_url": "https://realpython.com/python-exceptions/", "xp_value": 10},
            {"sequence": 5, "title": "Async / Await Basics", "resource_url": "https://realpython.com/async-io-python/", "xp_value": 20},
        ],
    },
    {
        "name": "FastAPI Craftsman",
        "level": "intermediate",
        "description": "Routing, Pydantic, auth, testing, deployment.",
        "checkpoints": [
            {"sequence": 1, "title": "Routing & Path Parameters", "resource_url": "https://fastapi.tiangolo.com/tutorial/path-params/", "xp_value": 10},
            {"sequence": 2, "title": "Pydantic Models & Validation", "resource_url": "https://fastapi.tiangolo.com/tutorial/body/", "xp_value": 15},
            {"sequence": 3, "title": "Dependency Injection", "resource_url": "https://fastapi.tiangolo.com/tutorial/dependencies/", "xp_value": 15},
            {"sequence": 4, "title": "Auth: OAuth2 + JWT", "resource_url": "https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/", "xp_value": 20},
            {"sequence": 5, "title": "Testing with pytest", "resource_url": "https://fastapi.tiangolo.com/tutorial/testing/", "xp_value": 15},
            {"sequence": 6, "title": "Docker Deployment", "resource_url": "https://fastapi.tiangolo.com/deployment/docker/", "xp_value": 20},
        ],
    },
    {
        "name": "SQL & Data Modeling",
        "level": "beginner",
        "description": "Normal forms, indexes, views, RLS, migrations.",
        "checkpoints": [
            {"sequence": 1, "title": "SELECT, WHERE, JOIN", "resource_url": "https://mode.com/sql-tutorial/", "xp_value": 10},
            {"sequence": 2, "title": "Normal Forms (1NF–3NF)", "resource_url": "https://www.brentozar.com/training/database-design/", "xp_value": 15},
            {"sequence": 3, "title": "Indexes & Query Plans", "resource_url": "https://use-the-index-luke.com/", "xp_value": 15},
            {"sequence": 4, "title": "Row-Level Security in Postgres", "resource_url": "https://supabase.com/docs/guides/auth/row-level-security", "xp_value": 20},
            {"sequence": 5, "title": "Migrations with Alembic", "resource_url": "https://alembic.sqlalchemy.org/en/latest/tutorial.html", "xp_value": 15},
        ],
    },
    {
        "name": "Git & GitHub Flow",
        "level": "beginner",
        "description": "Branching, PRs, rebasing, CI basics.",
        "checkpoints": [
            {"sequence": 1, "title": "Branching & Merging", "resource_url": "https://learngitbranching.js.org/", "xp_value": 10},
            {"sequence": 2, "title": "Pull Requests & Code Review", "resource_url": "https://docs.github.com/en/pull-requests", "xp_value": 10},
            {"sequence": 3, "title": "Rebasing vs Merging", "resource_url": "https://www.atlassian.com/git/tutorials/rewriting-history/git-rebase", "xp_value": 15},
            {"sequence": 4, "title": "GitHub Actions CI Basics", "resource_url": "https://docs.github.com/en/actions/quickstart", "xp_value": 15},
        ],
    },
    {
        "name": "System Design Basics",
        "level": "advanced",
        "description": "Caching, queuing, DB choice, API contracts.",
        "checkpoints": [
            {"sequence": 1, "title": "Caching Strategies (Redis, CDN)", "resource_url": "https://codeahoy.com/2017/08/11/caching-strategies-and-how-to-choose-the-right-one/", "xp_value": 20},
            {"sequence": 2, "title": "Message Queues vs Direct Calls", "resource_url": "https://aws.amazon.com/message-queue/", "xp_value": 20},
            {"sequence": 3, "title": "SQL vs NoSQL Decision Framework", "resource_url": "https://www.mongodb.com/nosql-explained/nosql-vs-sql", "xp_value": 20},
            {"sequence": 4, "title": "API Contract Design (OpenAPI)", "resource_url": "https://swagger.io/specification/", "xp_value": 20},
            {"sequence": 5, "title": "Architecture Review: Write Your Own ADR", "exercise": "Document one architectural decision from any of your active projects as an ADR using /journal decision.", "xp_value": 30},
        ],
    },
]


def seed(db):
    for track_data in BUILTIN_TRACKS:
        checkpoints = track_data.pop("checkpoints")

        result = (
            db.table("companion_tracks")
            .upsert(
                {**track_data, "is_builtin": True},
                on_conflict="name"
            )
            .execute()
        )
        track_id = result.data[0]["id"]
        print(f"Track: {track_data['name']} ({track_id})")

        for cp in checkpoints:
            db.table("companion_track_checkpoints").upsert(
                {"track_id": track_id, **cp},
                on_conflict="track_id,sequence"
            ).execute()
            print(f" * Checkpoint {cp['sequence']}: {cp['title']}")


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    print("Seeding built-in tracks...")
    seed(client)
    print("Done.")