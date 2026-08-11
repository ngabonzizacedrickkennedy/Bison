declare global {
  interface Window {
    bison: {
      gatewayHttpUrl: string;
      gatewayWebSocketUrl: string;
    };
  }
}

export {};
