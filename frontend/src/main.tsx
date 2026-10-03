// 不用 React.StrictMode：避免开发模式 effect 双执行造成 WebSocket 双连接。
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
