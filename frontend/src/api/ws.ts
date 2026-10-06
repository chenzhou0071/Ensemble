import type { WsEvent } from "../types";

export type WsHandlers = {
  onEvent: (evt: WsEvent) => void;
  onStatus: (status: "connecting" | "open" | "closed") => void;
};

/** 断线自动重连（指数退避），resume_from 定位到已收到的最大 seq（重放补齐）。 */
export class WsClient {
  private ws: WebSocket | null = null;
  private lastSeq = 0;
  private retry = 0;
  private closedByUser = false;

  constructor(
    private campaignId: string,
    private playerId: string,
    private clientId: string,
    private handlers: WsHandlers,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/campaign/${this.campaignId}` +
      `?player_id=${this.playerId}&resume_from=${this.lastSeq}` +
      `&client_id=${encodeURIComponent(this.clientId)}`;
    this.handlers.onStatus("connecting");
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.handlers.onStatus("open");
    };
    ws.onmessage = (msg: { data: string }) => {
      const evt = JSON.parse(msg.data) as WsEvent;
      if (evt.seq > this.lastSeq) this.lastSeq = evt.seq;
      this.handlers.onEvent(evt);
    };
    ws.onclose = () => {
      this.handlers.onStatus("closed");
      if (!this.closedByUser) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = Math.min(1000 * 2 ** this.retry, 15000);
    this.retry += 1;
    setTimeout(() => this.open(), delay);
  }

  sendInput(text: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "input", text }));
    }
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }
}
