import uvicorn

from app.config import ENV, HOST, IS_PRODUCTION, PORT


def main():
    print("\nWolfy")
    print(f"ENV: {ENV}")
    print(f"Open  http://localhost:{PORT}\n")
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=not IS_PRODUCTION,
    )


if __name__ == "__main__":
    main()
