// Stands in for Jev on OpenRouter's Decisions endpoint in the end-to-end tests:
// every claim it's asked about gets the same grade, an A at 2.4.
import { createServer, type ServerResponse } from "node:http";

const GRADE = {
  answers: {
    grade: {
      type: "score",
      score: 2.4,
      probabilities: { "0": 0.05, "1": 0.1, "2": 0.3, "3": 0.55 },
    },
    same_grounds: { type: "noul", noul: 0.9 },
    same_section: { type: "noul", noul: 0.2 },
  },
  model: "typesafe/jev-1.13",
  usage: { input_tokens: 300, output_tokens: 4, cost: 0.00002 },
  id: "e2e-decision",
  provider: "typesafe",
};

function reply(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

createServer((request, response) => {
  if (request.method === "POST" && request.url === "/api/alpha/decisions") {
    request.resume();
    request.on("end", () => {
      reply(response, 200, GRADE);
    });
  } else if (request.url === "/health") {
    reply(response, 200, { status: "ok" });
  } else {
    reply(response, 404, { error: "not_found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");
