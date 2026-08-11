const readPort = (value: string | undefined, fallback: number): number => {
  if (value === undefined) {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`invalid port: ${value}`);
  }
  return parsed;
};

export const config = {
  gatewayHost: process.env.BISON_GATEWAY_HOST ?? "127.0.0.1",
  gatewayPort: readPort(process.env.BISON_GATEWAY_PORT, 8000),
  devServerPort: readPort(process.env.BISON_RENDERER_PORT, 5173),
  isDevelopment: process.env.BISON_DESKTOP_DEV === "1",
} as const;

export const gatewayHttpUrl = `http://${config.gatewayHost}:${config.gatewayPort}`;
export const gatewayWebSocketUrl = `ws://${config.gatewayHost}:${config.gatewayPort}/ws`;
