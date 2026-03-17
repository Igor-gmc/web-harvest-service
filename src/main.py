from src.core.config import settings


def main() -> None:
    print("Application started")
    print(f"App name: {settings.app_name}")
    print(f"Environment: {settings.app_env}")
    print(f"Database URL: {settings.database_url}")
    print(f"Headless: {settings.playwright_headless}")


if __name__ == "__main__":
    main()