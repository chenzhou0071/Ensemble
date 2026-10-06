const KEY = "ensemble.client_id";

/** 浏览器客户端标识：首次访问生成并持久化，用于战役归属隔离（每人只见自己创建的档）。 */
export function getClientId(): string {
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) return existing;
    const id = randomHex();
    localStorage.setItem(KEY, id);
    return id;
  } catch {
    return randomHex();      // 隐私模式等不可写场景：本次会话内临时有效
  }
}

function randomHex(): string {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);   // 非 HTTPS 的纯 IP 部署也可用（randomUUID 要求安全上下文）
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}
