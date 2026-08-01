import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "2m", target: 25 },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://localhost:8000";
const apiKey = __ENV.API_KEY;

export default function () {
  if (!apiKey) {
    throw new Error("Set API_KEY before running the workload.");
  }
  const id = `${__VU}-${__ITER}`;
  const transactionId = `load-txn-${id}`;
  const eventId = `load-event-${id}`;
  const idempotencyKey = `load-idempotency-${id}`;
  const headers = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
  };
  const capture = {
    event_id: eventId,
    transaction_id: transactionId,
    event_type: "capture",
    card_id: `load-card-${__VU % 10}`,
    merchant_name: "Load Test Merchant",
    amount_minor: 1000 + (__ITER % 100),
    currency: "AUD",
    occurred_at: new Date().toISOString(),
  };

  const write = http.post(`${baseUrl}/v1/card-events`, JSON.stringify(capture), {
    headers,
  });
  check(write, {"capture accepted": (response) => response.status === 201});

  if (__ITER % 10 === 0) {
    const replay = http.post(`${baseUrl}/v1/card-events`, JSON.stringify(capture), {
      headers,
    });
    check(replay, {
      "replay stable": (response) =>
        response.status === 201 && response.headers["Idempotent-Replayed"] === "true",
    });
  }

  const read = http.get(`${baseUrl}/v1/transactions/${transactionId}`, {
    headers: {Authorization: `Bearer ${apiKey}`},
  });
  check(read, {"transaction readable": (response) => response.status === 200});
  sleep(0.2);
}
