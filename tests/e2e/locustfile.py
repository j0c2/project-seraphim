import os

from locust import HttpUser, between, tag, task

SLO_P95_MS = int(os.getenv("SLO_P95_MS", "100"))  # default 100ms
BASE_HOST = os.getenv("LOCUST_HOST")  # allow runtime override


class InferenceUser(HttpUser):
    wait_time = between(0.01, 0.1)
    if BASE_HOST:
        host = BASE_HOST

    @tag("predict")
    @task
    def predict(self):
        # Use catch_response to record failures on non-200 or slow responses
        with self.client.post(
            "/predict",
            json={"text": "hello world"},
            name="predict",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"non-200 status: {r.status_code}")
                return
            latency_ms = r.elapsed.total_seconds() * 1000.0
            if latency_ms > SLO_P95_MS:
                r.failure(f"latency {latency_ms:.1f}ms > SLO {SLO_P95_MS}ms")
            else:
                r.success()
