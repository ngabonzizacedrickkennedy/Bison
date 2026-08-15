const url = process.env.BISON_GATEWAY_WS ?? "ws://127.0.0.1:8000/ws";
const content = process.argv[2] ?? "hello from the probe";

const socket = new WebSocket(url);

const describe = (event) => {
  const payload = event.payload ?? {};

  if (event.type === "model.invoking") {
    return `${payload.role} → ${payload.model_id} (${payload.locality})`;
  }

  if (event.type === "model.responded") {
    return `${payload.latency_ms} ms`;
  }

  if (event.type === "message.persisted") {
    return `${payload.role}: ${payload.content}`;
  }

  if (event.type === "request.failed") {
    return `${payload.reason} ${JSON.stringify(payload.detail ?? null)}`;
  }

  return "";
};

socket.addEventListener("open", () => {
  console.log(`connected  ${url}`);
  socket.send(JSON.stringify({ type: "message.send", content }));
});

socket.addEventListener("message", (event) => {
  const parsed = JSON.parse(event.data);
  console.log(
    `seq ${String(parsed.sequence).padStart(2)}  ${parsed.type.padEnd(20)} ${describe(parsed)}`,
  );
  if (parsed.type === "request.completed" || parsed.type === "request.failed") {
    socket.close();
  }
});

socket.addEventListener("error", (event) => {
  console.error("error", event.message ?? event);
  process.exit(1);
});

socket.addEventListener("close", () => {
  console.log("closed");
});
