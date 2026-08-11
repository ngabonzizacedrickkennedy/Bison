import { contextBridge } from "electron";
import { gatewayHttpUrl, gatewayWebSocketUrl } from "./config";

contextBridge.exposeInMainWorld("bison", {
  gatewayHttpUrl,
  gatewayWebSocketUrl,
});
