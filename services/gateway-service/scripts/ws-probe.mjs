const url = process.env.BISON_GATEWAY_WS ?? "ws://127.0.0.1:8000/ws";
const content = process.argv[2] ?? "hello from the probe";

const socket = new WebSocket(url);

socket.addEventListener("open", () => {
  console.log(`connected  ${url}`);
  socket.send(JSON.stringify({ type: "message.send", content }));
});

socket.addEventListener("message", (event) => {
  const parsed = JSON.parse(event.data);
  console.log(
    `seq ${String(parsed.sequence).padStart(2)}  ${parsed.type.padEnd(20)} ${parsed.request_id}`,
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
