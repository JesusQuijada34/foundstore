"""Task entry point for the Render cron service.

It only removes expired, short-lived records. It does not ping the web service and
therefore must not be used as a false guarantee that a free instance never sleeps.
"""

from app import app


def main() -> None:
    store = app.extensions["device_store"]
    result = store.maintain()
    print({"storage": store.backend_name, **result}, flush=True)


if __name__ == "__main__":
    main()
